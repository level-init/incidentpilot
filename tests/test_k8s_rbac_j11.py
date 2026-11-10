"""J11: narrow K8s RBAC for remediation identities.

Static kubeauth over manifests always runs. Live kind/k3d checks run only when
``INCIDENTPILOT_KIND=1`` and ``kubectl`` can talk to a cluster.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class AccessRequest:
    verb: str
    group: str
    resource: str
    namespace: str | None


def _rule_matches(rule: dict[str, Any], req: AccessRequest) -> bool:
    groups = list(rule.get("apiGroups") or [])
    resources = list(rule.get("resources") or [])
    verbs = list(rule.get("verbs") or [])
    if "*" not in groups and req.group not in groups:
        return False
    if "*" not in resources and req.resource not in resources:
        return False
    if "*" not in verbs and req.verb not in verbs:
        return False
    return True


def can_i(
    *,
    roles: Iterable[dict[str, Any]],
    cluster_roles: Iterable[dict[str, Any]] = (),
    req: AccessRequest,
) -> bool:
    """SubjectAccessReview-style check over Role rules (no live apiserver)."""
    if req.namespace is None:
        for cr in cluster_roles:
            for rule in cr.get("rules") or []:
                if _rule_matches(rule, req):
                    return True
        return False
    for role in roles:
        meta = role.get("metadata") or {}
        if meta.get("namespace") != req.namespace:
            continue
        for rule in role.get("rules") or []:
            if _rule_matches(rule, req):
                return True
    return False

K8S = REPO / "deploy" / "k8s"
REMEDIATION = K8S / "remediation"
APPROVED_NS = frozenset(
    {
        "sim-checkout",
        "sim-payment",
        "sim-gateway",
        "sim-auth",
        "sim-inventory",
        "sim-notification",
    }
)
SA_NAME = "incidentpilot-remediation"
SA_NS = "incidentpilot-system"
ROLE_NAME = "incidentpilot-remediation-mutate"

FORBIDDEN_VERBS = frozenset({"*", "escalate", "bind", "impersonate"})
FORBIDDEN_RESOURCES = frozenset({"*", "secrets", "serviceaccounts", "namespaces"})


def _load_docs(path: Path) -> list[dict]:
    docs: list[dict] = []
    for doc in yaml.safe_load_all(path.read_text()):
        if isinstance(doc, dict) and doc.get("kind"):
            docs.append(doc)
    return docs


def _all_remediation_docs() -> list[dict]:
    docs: list[dict] = []
    for path in sorted(REMEDIATION.glob("*.yaml")):
        if path.name == "kustomization.yaml":
            continue
        docs.extend(_load_docs(path))
    for path in sorted((K8S / "namespaces").glob("*.yaml")):
        docs.extend(_load_docs(path))
    return docs


def _roles() -> list[dict]:
    return [d for d in _all_remediation_docs() if d.get("kind") == "Role"]


def _rolebindings() -> list[dict]:
    return [d for d in _all_remediation_docs() if d.get("kind") == "RoleBinding"]


def _canonical_rules() -> list[dict]:
    roles = [d for d in _load_docs(REMEDIATION / "role.yaml") if d.get("kind") == "Role"]
    assert len(roles) == 1
    return list(roles[0]["rules"])


def test_no_cluster_role_or_binding_for_remediation() -> None:
    kinds = {d.get("kind") for d in _all_remediation_docs()}
    assert "ClusterRole" not in kinds
    assert "ClusterRoleBinding" not in kinds


def test_serviceaccount_is_remediation_only() -> None:
    sas = [d for d in _all_remediation_docs() if d.get("kind") == "ServiceAccount"]
    assert len(sas) == 1
    sa = sas[0]
    assert sa["metadata"]["name"] == SA_NAME
    assert sa["metadata"]["namespace"] == SA_NS
    assert sa["metadata"]["labels"]["incidentpilot.io/privilege-class"] == "remediation"


def test_rolebindings_only_in_approved_namespaces() -> None:
    rbs = _rolebindings()
    assert {rb["metadata"]["namespace"] for rb in rbs} == APPROVED_NS
    for rb in rbs:
        assert rb["roleRef"]["kind"] == "Role"
        assert rb["roleRef"]["name"] == ROLE_NAME
        subjects = rb["subjects"]
        assert len(subjects) == 1
        assert subjects[0]["kind"] == "ServiceAccount"
        assert subjects[0]["name"] == SA_NAME
        assert subjects[0]["namespace"] == SA_NS


def test_roles_match_canonical_and_forbid_wildcards() -> None:
    canonical = _canonical_rules()
    roles = [r for r in _roles() if r["metadata"]["name"] == ROLE_NAME]
    assert {r["metadata"]["namespace"] for r in roles} == APPROVED_NS
    for role in roles:
        assert role["rules"] == canonical
        for rule in role["rules"]:
            assert not FORBIDDEN_VERBS.intersection(rule.get("verbs") or [])
            assert not FORBIDDEN_RESOURCES.intersection(rule.get("resources") or [])
            assert "*" not in (rule.get("apiGroups") or [])


def test_kubeauth_can_patch_allowed_workloads() -> None:
    roles = [r for r in _roles() if r["metadata"]["name"] == ROLE_NAME]
    for ns in APPROVED_NS:
        assert can_i(
            roles=roles,
            req=AccessRequest(
                verb="patch",
                group="apps",
                resource="deployments",
                namespace=ns,
            ),
        )
        assert can_i(
            roles=roles,
            req=AccessRequest(
                verb="patch",
                group="apps",
                resource="deployments/scale",
                namespace=ns,
            ),
        )
        assert can_i(
            roles=roles,
            req=AccessRequest(
                verb="delete",
                group="",
                resource="pods",
                namespace=ns,
            ),
        )


def test_kubeauth_denied_outside_approved_namespace() -> None:
    roles = [r for r in _roles() if r["metadata"]["name"] == ROLE_NAME]
    for ns in ("kube-system", "default", "incidentpilot-system"):
        assert not can_i(
            roles=roles,
            req=AccessRequest(
                verb="patch",
                group="apps",
                resource="deployments",
                namespace=ns,
            ),
        )


def test_kubeauth_cannot_cluster_admin() -> None:
    roles = [r for r in _roles() if r["metadata"]["name"] == ROLE_NAME]
    assert not can_i(
        roles=roles,
        cluster_roles=[],
        req=AccessRequest(
            verb="*",
            group="*",
            resource="*",
            namespace=None,
        ),
    )
    assert not can_i(
        roles=roles,
        req=AccessRequest(
            verb="get",
            group="",
            resource="secrets",
            namespace="sim-checkout",
        ),
    )


def _kind_enabled() -> bool:
    return os.environ.get("INCIDENTPILOT_KIND") == "1"


def _kubectl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kubectl", *args],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not _kind_enabled(), reason="set INCIDENTPILOT_KIND=1 for kind kubeauth")
def test_kind_kubeauth_can_and_cannot() -> None:
    apply = _kubectl("apply", "-k", str(REMEDIATION))
    assert apply.returncode == 0, apply.stderr

    as_sa = f"system:serviceaccount:{SA_NS}:{SA_NAME}"

    allow = _kubectl(
        "auth",
        "can-i",
        "patch",
        "deployments.apps",
        f"--as={as_sa}",
        "-n",
        "sim-checkout",
    )
    assert allow.returncode == 0
    assert allow.stdout.strip().lower() == "yes"

    deny = _kubectl(
        "auth",
        "can-i",
        "patch",
        "deployments.apps",
        f"--as={as_sa}",
        "-n",
        "kube-system",
    )
    assert deny.stdout.strip().lower() == "no"

    star = _kubectl(
        "auth",
        "can-i",
        "*",
        "*",
        f"--as={as_sa}",
        "--all-namespaces",
    )
    assert star.stdout.strip().lower() == "no"
