"""Resolve LLMProvider from env — general worker only (H1)."""

from __future__ import annotations

import os

from incidentpilot_adapters.llm.fake import FakeLLMProvider
from incidentpilot_adapters.llm.protocol import LLMProvider


def resolve_llm_provider() -> LLMProvider:
    """Pick provider from ``LLM_PROVIDER`` (default ``fake`` for local/tests).

    Live API keys (``OPENAI_API_KEY`` / ``LLM_API_KEY``) belong on the general
    ``incidentpilot-worker`` only — never on evidence- or remediation-worker.
    """
    name = (os.environ.get("LLM_PROVIDER") or "fake").strip().lower()
    model = os.environ.get("LLM_MODEL") or "fake-test"
    if name in {"fake", "test", "none", ""}:
        return FakeLLMProvider(model=model)
    # Real vendors land later; refuse silent fallback that invents answers.
    raise RuntimeError(
        f"LLM_PROVIDER={name!r} is not configured in this build; "
        "use LLM_PROVIDER=fake for local, or add a vendor adapter"
    )
