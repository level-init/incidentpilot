"""O6: Temporal Cloud wiring (config, secrets, connect helpers, fallback docs)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "incidentpilot"
TF_SECRETS = ROOT / "deploy" / "terraform" / "modules" / "secrets"


def test_docs_and_smoke_script() -> None:
    assert (ROOT / "docs/temporal-cloud.md").is_file()
    script = ROOT / "scripts/temporal_cloud_smoke.sh"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "TEMPORAL_API_KEY" in text
    assert "temporal-queue-smoke" in text


def test_terraform_temporal_cloud_secret() -> None:
    main = (TF_SECRETS / "main.tf").read_text(encoding="utf-8")
    outs = (TF_SECRETS / "outputs.tf").read_text(encoding="utf-8")
    assert "aws_secretsmanager_secret" in main
    assert "temporal_cloud" in main
    assert "api_key" in main
    assert "temporal_cloud_secret_arn" in outs
    assert "temporal_cloud" in outs


def test_helm_staging_prefers_cloud() -> None:
    staging = yaml.safe_load((CHART / "values-staging.yaml").read_text(encoding="utf-8"))
    demo = yaml.safe_load(
        (CHART / "values-production-demo.yaml").read_text(encoding="utf-8")
    )
    local = yaml.safe_load((CHART / "values-local.yaml").read_text(encoding="utf-8"))
    assert staging["config"]["temporal"]["hosting"] == "cloud"
    assert staging["config"]["temporal"]["tls"] is True
    assert staging["config"]["temporal"]["apiKeySecretName"]
    assert demo["config"]["temporal"]["hosting"] == "cloud"
    assert local["config"]["temporal"]["hosting"] == "selfhosted"


def test_helm_helpers_emit_temporal_address_not_only_host() -> None:
    helpers = (CHART / "templates/_helpers.tpl").read_text(encoding="utf-8")
    assert "TEMPORAL_ADDRESS" in helpers
    assert "TEMPORAL_API_KEY" in helpers
    assert "TEMPORAL_HOSTING" in helpers


def test_network_policy_cloud_egress() -> None:
    text = (
        ROOT / "deploy/k8s/networkpolicies/system-allowlists.yaml"
    ).read_text(encoding="utf-8")
    assert "allow-temporal-cloud-egress" in text
    assert "incidentpilot.io/temporal-hosting: cloud" in text


def test_connect_temporal_passes_tls_and_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from incidentpilot_shared import temporal_runtime as tr

    monkeypatch.setenv("TEMPORAL_ADDRESS", "demo.a1b2.tmprl.cloud:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "demo.a1b2")
    monkeypatch.setenv("TEMPORAL_API_KEY", "test-key")
    monkeypatch.delenv("TEMPORAL_TLS", raising=False)

    assert tr.temporal_hosting_mode() == "cloud"
    assert tr.temporal_tls_enabled() is True

    captured: dict = {}

    async def fake_connect(target: str, **kwargs):
        captured["target"] = target
        captured["kwargs"] = kwargs

        class _C:
            pass

        return _C()

    with mock.patch.object(tr.Client, "connect", side_effect=fake_connect):
        import asyncio

        asyncio.run(tr.connect_temporal())

    assert captured["target"] == "demo.a1b2.tmprl.cloud:7233"
    assert captured["kwargs"]["namespace"] == "demo.a1b2"
    assert captured["kwargs"]["api_key"] == "test-key"
    assert captured["kwargs"]["tls"] is True


def test_connect_selfhosted_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    from incidentpilot_shared import temporal_runtime as tr

    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "default")
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    monkeypatch.setenv("TEMPORAL_TLS", "false")
    monkeypatch.setenv("TEMPORAL_HOSTING", "selfhosted")

    assert tr.temporal_hosting_mode() == "selfhosted"
    assert tr.temporal_tls_enabled() is False

    captured: dict = {}

    async def fake_connect(target: str, **kwargs):
        captured["target"] = target
        captured["kwargs"] = kwargs

        class _C:
            pass

        return _C()

    with mock.patch.object(tr.Client, "connect", side_effect=fake_connect):
        import asyncio

        asyncio.run(tr.connect_temporal())

    assert captured["target"] == "localhost:7233"
    assert "api_key" not in captured["kwargs"]
    assert captured["kwargs"].get("tls") is not True


def test_address_falls_back_from_temporal_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from incidentpilot_shared import temporal_runtime as tr

    monkeypatch.delenv("TEMPORAL_ADDRESS", raising=False)
    monkeypatch.setenv("TEMPORAL_HOST", "temporal-frontend:7233")
    assert tr.temporal_address() == "temporal-frontend:7233"
