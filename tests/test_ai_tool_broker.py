"""H3: AI tool broker — READ/PROPOSE/COLLECTOR_TRIGGER; deny POLICY_EVAL/ACTION_EXECUTE."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from incidentpilot_shared.ai_tool_broker import AiToolBroker, ToolInvocationResult
from incidentpilot_shared.ai_tools import (
    DENIED_TOOL_NAMES,
    ToolCapability,
    ToolDeniedError,
    default_ai_tool_registry,
)
from incidentpilot_shared.redaction import RedactionError
from incidentpilot_shared.tool_scope import ScopeViolationError, ToolScope

ROOT = Path(__file__).resolve().parents[1]
INCIDENT = str(uuid4())
EVIDENCE = str(uuid4())


def _scope(*, owned: frozenset[str] | None = None) -> ToolScope:
    return ToolScope(
        incident_id=INCIDENT,
        environment="local",
        owned_resource_ids=owned or frozenset(),
    )


def _broker(**kwargs: Any) -> AiToolBroker:
    return AiToolBroker(scope=_scope(), **kwargs)


def test_policy_eval_denied() -> None:
    broker = _broker()
    with pytest.raises(ToolDeniedError, match="denied"):
        broker.invoke("POLICY_EVAL", {"incident_id": INCIDENT})


def test_action_execute_denied() -> None:
    broker = _broker()
    with pytest.raises(ToolDeniedError, match="denied"):
        broker.invoke("ACTION_EXECUTE", {"incident_id": INCIDENT, "action_id": "a1"})


@pytest.mark.parametrize("denied", sorted(DENIED_TOOL_NAMES))
def test_denied_matrix_rejected_at_broker(denied: str) -> None:
    broker = _broker()
    with pytest.raises(ToolDeniedError):
        broker.invoke(denied, {"incident_id": INCIDENT})


def test_allow_list_capabilities_exclude_execute_and_policy() -> None:
    broker = _broker()
    caps = {spec.capability for spec in broker._registry.list_for_ai_sandbox()}
    assert ToolCapability.READ in caps
    assert ToolCapability.PROPOSE in caps
    assert ToolCapability.COLLECTOR_TRIGGER in caps
    assert {c.value for c in caps}.isdisjoint({"ACTION_EXECUTE", "POLICY_EVAL", "EXECUTE"})


def test_action_propose_does_not_execute() -> None:
    calls: list[str] = []

    def fake_reserve(*_a: object, **_k: object) -> None:
        calls.append("reserve")

    broker = _broker()
    # Monkeypatch attribute must not exist / not be called — invoke propose only.
    result = broker.invoke(
        "action_propose",
        {
            "incident_id": INCIDENT,
            "action_type": "rollback",
            "rationale": "error spike",
            "parameters": {"revision": "prev"},
        },
    )
    assert isinstance(result, ToolInvocationResult)
    assert result.ok is True
    assert result.capability == ToolCapability.PROPOSE
    assert result.data is not None
    assert result.data["executed"] is False
    assert result.data["authorized"] is False
    assert calls == []
    del fake_reserve


def test_hypothesis_propose_ok() -> None:
    result = _broker().invoke(
        "hypothesis_propose",
        {
            "incident_id": INCIDENT,
            "statement": "bad deploy",
            "cited_evidence_ids": ["EV-1"],
            "confidence": 0.6,
        },
    )
    assert result.ok is True
    assert result.capability == ToolCapability.PROPOSE
    assert result.data is not None
    assert result.data["executed"] is False


def test_telemetry_read_exploratory_without_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_URL", "http://should-not-be-read")
    monkeypatch.setenv("LOKI_URL", "http://should-not-be-read")
    seen: list[str] = []

    class GuardedEnviron(dict):
        def __getitem__(self, key: str) -> str:  # type: ignore[override]
            seen.append(key)
            return super().__getitem__(key)

    result = _broker().invoke(
        "telemetry_read",
        {"incident_id": INCIDENT, "query": "up", "window_seconds": 60},
    )
    assert result.ok is True
    assert result.capability == ToolCapability.READ
    assert result.data is not None
    assert result.data["evidence_authorship"] is False
    assert result.data["mode"] == "exploratory"
    assert "PROMETHEUS_URL" not in seen
    assert "LOKI_URL" not in seen


def test_telemetry_read_uses_injected_explorer() -> None:
    class FakeExplorer:
        def explore(self, **kwargs: Any) -> dict[str, Any]:
            return {"samples": [{"metric": "up", "value": 1}], "query": kwargs["query"]}

    result = _broker(telemetry_explorer=FakeExplorer()).invoke(
        "telemetry_read",
        {"incident_id": INCIDENT, "query": "up{job=api}", "window_seconds": 120},
    )
    assert result.ok is True
    assert result.data is not None
    assert result.data["samples"][0]["value"] == 1
    assert result.data["evidence_authorship"] is False


def test_collector_trigger_allowed_injects_bound_env() -> None:
    payloads: list[dict[str, Any]] = []

    def starter(payload: dict[str, Any]) -> dict[str, Any]:
        payloads.append(payload)
        return {"started": True, "workflow_id": "collect-1"}

    result = _broker(collector_trigger=starter).invoke(
        "collector_trigger",
        {"incident_id": INCIDENT, "collector": "logs", "query": "{app=checkout}"},
    )
    assert result.ok is True
    assert result.capability == ToolCapability.COLLECTOR_TRIGGER
    assert payloads == [
        {
            "incident_id": INCIDENT,
            "environment": "local",
            "collector": "logs",
            "query": "{app=checkout}",
        }
    ]
    assert result.data == {"started": True, "workflow_id": "collect-1"}


def test_collector_trigger_requires_handler() -> None:
    with pytest.raises(RuntimeError, match="not configured"):
        _broker().invoke(
            "collector_trigger",
            {"incident_id": INCIDENT, "collector": "metrics", "query": "up"},
        )


def test_cross_incident_denied() -> None:
    broker = _broker()
    with pytest.raises(ScopeViolationError, match="cross-incident"):
        broker.invoke(
            "telemetry_read",
            {"incident_id": "other-inc", "query": "up", "window_seconds": 60},
        )


def test_evidence_id_not_owned_denied() -> None:
    broker = AiToolBroker(scope=_scope(owned=frozenset({"ev-owned"})))
    with pytest.raises(ScopeViolationError, match="not owned"):
        broker.invoke(
            "evidence_projection_read",
            {"incident_id": INCIDENT, "evidence_id": "ev-foreign"},
        )


def test_evidence_projection_read_requires_conn() -> None:
    broker = AiToolBroker(scope=_scope(owned=frozenset({EVIDENCE})))
    with pytest.raises(RuntimeError, match="database connection"):
        broker.invoke(
            "evidence_projection_read",
            {"incident_id": INCIDENT, "evidence_id": EVIDENCE},
        )


def test_evidence_projection_read_uses_projection_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    from incidentpilot_shared.redaction import EvidenceProjection

    calls: list[tuple[str, str]] = []

    def fake_read(conn: object, *, incident_id: object, evidence_id: object) -> EvidenceProjection:
        calls.append((str(incident_id), str(evidence_id)))
        assert conn is sentinel
        return EvidenceProjection(
            summary="safe summary",
            structured_data={"msg": "ok"},
            redacted_fields=("password",),
        )

    import incidentpilot_shared.ai_tool_broker as broker_mod

    monkeypatch.setattr(broker_mod, "read_evidence_projection_for_llm", fake_read)
    sentinel = object()
    broker = AiToolBroker(
        scope=_scope(owned=frozenset({EVIDENCE})),
        conn=sentinel,  # type: ignore[arg-type]
    )
    result = broker.invoke(
        "evidence_projection_read",
        {"incident_id": INCIDENT, "evidence_id": EVIDENCE},
    )
    assert result.ok is True
    assert result.data is not None
    assert result.data["summary"] == "safe summary"
    assert result.data["source"] == "evidence_projection"
    assert "password" not in str(result.data["structured_data"])
    assert calls == [(INCIDENT, EVIDENCE)]


def test_blocked_projection_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import incidentpilot_shared.ai_tool_broker as broker_mod

    def boom(*_a: object, **_k: object) -> None:
        raise RedactionError("blocked")

    monkeypatch.setattr(broker_mod, "read_evidence_projection_for_llm", boom)
    broker = AiToolBroker(
        scope=_scope(owned=frozenset({EVIDENCE})),
        conn=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(RedactionError, match="blocked"):
        broker.invoke(
            "evidence_projection_read",
            {"incident_id": INCIDENT, "evidence_id": EVIDENCE},
        )


def test_broker_module_has_no_policy_or_execute_handlers() -> None:
    path = ROOT / "shared" / "incidentpilot_shared" / "ai_tool_broker.py"
    text = path.read_text(encoding="utf-8")
    # Dispatch arms are string equality on allow-listed names only.
    assert '== "POLICY_EVAL"' not in text
    assert '== "ACTION_EXECUTE"' not in text
    assert '== "policy_eval"' not in text
    assert '== "action_execute"' not in text
    assert "reserve_execution_attempt" not in text
    assert "decide_approval" not in text
    assert "PROMETHEUS_URL" not in text
    assert "append_evidence_command" not in text


def test_schemas_for_llm_matches_registry() -> None:
    broker = _broker()
    assert set(broker.schemas_for_llm()) == {
        spec.name for spec in default_ai_tool_registry().list_for_ai_sandbox()
    }
