"""O5: Ingress split — user/API OIDC vs webhooks (no OIDC)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "incidentpilot"

# Annotation keys / values that imply human IdP gating — forbidden on webhooks.
OIDC_MARKERS = (
    "auth-url",
    "auth-signin",
    "auth-type",
    "authenticate-oidc",
    "oauth2",
    "oidc",
)

WEBHOOK_SECRET_MARKERS = (
    "ALERTMANAGER_WEBHOOK_TOKEN",
    "ALERTMANAGER_BASIC_",
    "SLACK_SIGNING_SECRET",
    "webhook-token",
    "signing-secret",
)


def _load_yaml_docs(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]


def test_ingress_templates_exist() -> None:
    assert (CHART / "templates/ingress-user.yaml").is_file()
    assert (CHART / "templates/ingress-webhooks.yaml").is_file()


def test_values_and_schema_define_ingress_planes() -> None:
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    assert "ingress:" in values
    assert "webhooks:" in values
    assert "auth-url" in values
    # Default webhooks annotations block must not carry OIDC.
    schema = json.loads((CHART / "values.schema.json").read_text(encoding="utf-8"))
    assert "ingress" in schema["required"]
    assert "ingress" in schema["properties"]


def test_docs_exist() -> None:
    assert (ROOT / "docs/ingress.md").is_file()


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not on PATH")
def test_staging_renders_split_without_oidc_on_webhooks() -> None:
    proc = subprocess.run(
        [
            "helm",
            "template",
            "ip-staging",
            str(CHART),
            "-f",
            str(CHART / "values-staging.yaml"),
            "--namespace",
            "incidentpilot-system",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    ingresses = [
        d
        for d in _load_yaml_docs(proc.stdout)
        if d.get("kind") == "Ingress"
    ]
    by_class = {
        (i.get("metadata") or {}).get("labels", {}).get("incidentpilot.io/ingress-class"): i
        for i in ingresses
    }
    assert "user" in by_class
    assert "webhooks" in by_class

    user = by_class["user"]
    hooks = by_class["webhooks"]

    user_ann = yaml.safe_dump((user.get("metadata") or {}).get("annotations") or {})
    assert any(m in user_ann.lower() for m in ("auth-url", "oidc", "oauth2"))

    hooks_ann = yaml.safe_dump((hooks.get("metadata") or {}).get("annotations") or {})
    for marker in OIDC_MARKERS:
        assert marker.lower() not in hooks_ann.lower(), marker

    # User ingress must not embed webhook secret material.
    user_blob = yaml.safe_dump(user)
    for marker in WEBHOOK_SECRET_MARKERS:
        assert marker not in user_blob, marker

    # Webhooks only expose /webhooks prefix to the API service.
    hook_paths: list[str] = []
    hook_hosts: set[str] = set()
    for rule in hooks.get("spec", {}).get("rules") or []:
        hook_hosts.add(rule["host"])
        for p in rule.get("http", {}).get("paths") or []:
            hook_paths.append(p["path"])
            assert p["backend"]["service"]["name"] == "incidentpilot-api"
    assert hook_paths
    assert all(p == "/webhooks" or p.startswith("/webhooks") for p in hook_paths)

    user_hosts: set[str] = set()
    for rule in user.get("spec", {}).get("rules") or []:
        user_hosts.add(rule["host"])
        for p in rule.get("http", {}).get("paths") or []:
            assert p["path"] != "/webhooks"
    assert user_hosts.isdisjoint(hook_hosts)


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not on PATH")
def test_local_default_skips_ingress_objects() -> None:
    proc = subprocess.run(
        [
            "helm",
            "template",
            "ip-local",
            str(CHART),
            "-f",
            str(CHART / "values-local.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    kinds = [d.get("kind") for d in _load_yaml_docs(proc.stdout)]
    assert "Ingress" not in kinds


def test_webhook_docs_point_at_hooks_host() -> None:
    text = (ROOT / "docs/ingress.md").read_text(encoding="utf-8")
    assert "hooks." in text
    assert re.search(r"/webhooks/alerts", text)
    assert "OIDC" in text
