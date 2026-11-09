"""Registered Evidence producers (G1).

Only allow-listed identities may write ``domain.evidence``. AI sandbox is never
a producer — roles ≠ trust.
"""

from __future__ import annotations

from typing import Final

from incidentpilot_shared.ai_tools import AI_SANDBOX_IDENTITY

# Named collectors / system producers (extend as G3+ lands).
REGISTERED_EVIDENCE_PRODUCERS: Final[frozenset[str]] = frozenset(
    {
        "prometheus_collector",
        "loki_collector",
        "tempo_collector",
        "change_collector",
        "alert_context",
        "deterministic_processor",
        "runbook_store",
        "test_producer",
    }
)


class EvidenceProducerDenied(PermissionError):
    """Raised when a non-registered identity attempts to write Evidence."""


def is_registered_evidence_producer(producer: str) -> bool:
    name = (producer or "").strip()
    if not name:
        return False
    if name == AI_SANDBOX_IDENTITY or name.startswith("ai_"):
        return False
    # Human session observations: session:<actor_id>
    if name.startswith("session:") and len(name) > len("session:"):
        return True
    return name in REGISTERED_EVIDENCE_PRODUCERS


def assert_registered_evidence_producer(producer: str) -> str:
    name = (producer or "").strip()
    if not is_registered_evidence_producer(name):
        raise EvidenceProducerDenied(f"evidence producer not registered or denied: {producer!r}")
    return name
