"""O4: NetworkPolicies default-deny + allowlists; GT unreachable from IP workers."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NP = ROOT / "deploy" / "k8s" / "networkpolicies"


def _load_all() -> list[dict]:
    docs: list[dict] = []
    for path in sorted(NP.glob("*.yaml")):
        if path.name == "kustomization.yaml":
            continue
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if isinstance(doc, dict) and doc.get("kind") == "NetworkPolicy":
                docs.append(doc)
    return docs


def test_kustomization_lists_policy_files() -> None:
    text = (NP / "kustomization.yaml").read_text(encoding="utf-8")
    for name in (
        "system-default-deny.yaml",
        "system-allowlists.yaml",
        "eval-default-deny.yaml",
        "eval-allowlists.yaml",
    ):
        assert name in text


def test_default_deny_on_both_planes() -> None:
    policies = _load_all()
    by_ns: dict[str, list[str]] = {}
    for p in policies:
        ns = p["metadata"]["namespace"]
        by_ns.setdefault(ns, []).append(p["metadata"]["name"])
    assert "incidentpilot-system" in by_ns
    assert "incidentpilot-eval" in by_ns
    assert "default-deny-ingress" in by_ns["incidentpilot-system"]
    assert "default-deny-egress" in by_ns["incidentpilot-system"]
    assert "default-deny-ingress" in by_ns["incidentpilot-eval"]
    assert "default-deny-egress" in by_ns["incidentpilot-eval"]


def test_no_system_to_eval_allow_path() -> None:
    """Control-plane policies must not open paths into the eval namespace."""
    for p in _load_all():
        if p["metadata"]["namespace"] != "incidentpilot-system":
            continue
        blob = yaml.safe_dump(p)
        assert "incidentpilot-eval" not in blob
        assert 'plane: eval' not in blob
        assert "incidentpilot.io/plane: eval" not in blob


def test_eval_ingress_not_from_control_plane() -> None:
    for p in _load_all():
        if p["metadata"]["namespace"] != "incidentpilot-eval":
            continue
        for rule in (p.get("spec") or {}).get("ingress") or []:
            for src in rule.get("from") or []:
                ns = (src.get("namespaceSelector") or {}).get("matchLabels") or {}
                assert ns.get("kubernetes.io/metadata.name") != "incidentpilot-system"
                assert ns.get("incidentpilot.io/plane") != "control"


def test_allowlists_cover_dns_temporal_postgres() -> None:
    names = {p["metadata"]["name"] for p in _load_all()}
    assert "allow-dns" in names
    assert "allow-temporal-egress" in names or "allow-runner-temporal-egress" in names
    assert "allow-postgres-egress" in names


def test_helm_pods_carry_privilege_class_label() -> None:
    helpers = (
        ROOT / "deploy/helm/incidentpilot/templates/_helpers.tpl"
    ).read_text(encoding="utf-8")
    assert "incidentpilot.io/privilege-class" in helpers


def test_docs_exist() -> None:
    assert (ROOT / "docs/network-policies.md").is_file()
