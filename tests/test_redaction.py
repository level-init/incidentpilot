"""C4: redaction projections — secrets absent; canonical Evidence unchanged."""

from __future__ import annotations

import copy

import pytest

from incidentpilot_shared.redaction import (
    RedactionError,
    RedactionRule,
    project_evidence_for_llm,
    supply_projection_to_llm,
)


def test_secrets_absent_from_projection() -> None:
    canonical = {
        "log": (
            "deploy failed auth=Bearer eyJhbGciOiJIUzI1NiJ9.aaaa.bbbb "
            "aws_key=AKIAIOSFODNN7EXAMPLE "
            "user=oncall@example.com "
            "api_key=supersecretvalue123"
        ),
        "meta": {"slack": "xoxb-1234567890-abcdefghij"},
        "nested": [{"token": "ghp_abcdefghijklmnopqrstuvwxyz0123456789"}],
    }
    before = copy.deepcopy(canonical)

    projection = project_evidence_for_llm(
        summary="password=hunter2password alert for oncall@example.com",
        structured_data=canonical,
    )

    blob = projection.summary + str(projection.structured_data)
    assert "AKIAIOSFODNN7EXAMPLE" not in blob
    assert "eyJhbGciOiJIUzI1NiJ9" not in blob
    assert "xoxb-1234567890-abcdefghij" not in blob
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in blob
    assert "supersecretvalue123" not in blob
    assert "hunter2password" not in blob
    assert "oncall@example.com" not in blob
    assert "[REDACTED:" in blob
    assert canonical == before


def test_canonical_structured_data_unchanged() -> None:
    secret = "AKIAIOSFODNN7EXAMPLE"
    canonical = {"access_key": secret, "note": "keep me"}
    identity = id(canonical)
    inner_id = id(canonical["access_key"])

    projection = project_evidence_for_llm(
        summary="ok",
        structured_data=canonical,
    )

    assert id(canonical) == identity
    assert canonical["access_key"] is not projection.structured_data["access_key"]
    assert canonical["access_key"] == secret
    assert id(canonical["access_key"]) == inner_id
    assert secret not in projection.structured_data["access_key"]
    assert projection.structured_data["note"] == "keep me"


def test_failed_redaction_blocked_from_llm_supply() -> None:
    """Unsupported types must raise — caller must not invoke the LLM."""
    with pytest.raises(RedactionError, match="unsupported value type"):
        supply_projection_to_llm(
            summary="ok",
            structured_data={"blob": b"\x00secret-bytes"},
        )


def test_residual_secret_fails_closed() -> None:
    """If a rule cannot scrub a known secret shape, refuse LLM supply."""
    noop = (
        RedactionRule(
            name="noop",
            pattern=__import__("re").compile(r"(?!x)x"),
            replacement="[REDACTED:noop]",
        ),
    )
    with pytest.raises(RedactionError, match="residual secret"):
        project_evidence_for_llm(
            summary="key AKIAIOSFODNN7EXAMPLE",
            structured_data={},
            rules=noop,
        )


def test_connection_string_password_redacted() -> None:
    canonical = {
        "dsn": "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    }
    projection = project_evidence_for_llm(summary="db", structured_data=canonical)
    assert "incidentpilot_app" not in projection.structured_data["dsn"]
    assert "[REDACTED:connection_password]" in projection.structured_data["dsn"]
    assert canonical["dsn"].endswith("@localhost:5432/incidentpilot")


def test_private_key_block_redacted() -> None:
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF6PZGBm48Ah+SLw5QxX\n"
        "-----END RSA PRIVATE KEY-----"
    )
    canonical = {"key": pem}
    projection = project_evidence_for_llm(summary="tls", structured_data=canonical)
    assert "BEGIN RSA PRIVATE KEY" not in projection.structured_data["key"]
    assert projection.structured_data["key"] == "[REDACTED:private_key]"
    assert "BEGIN RSA PRIVATE KEY" in canonical["key"]
