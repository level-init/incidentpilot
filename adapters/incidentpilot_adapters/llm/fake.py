"""FakeLLMProvider for unit tests (H1)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from incidentpilot_adapters.llm.protocol import LLMRequest, LLMResult


class FakeLLMProvider:
    """Scriptable provider — returns canned text; never touches domain."""

    def __init__(
        self,
        *,
        name: str = "fake",
        model: str = "fake-test",
        responses: list[str] | None = None,
        handler: Callable[[LLMRequest], str] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._responses = list(responses or [])
        self._handler = handler
        self._calls: list[LLMRequest] = []

    @property
    def calls(self) -> list[LLMRequest]:
        return list(self._calls)

    def complete(self, request: LLMRequest) -> LLMResult:
        started = time.perf_counter()
        self._calls.append(request)
        if self._handler is not None:
            raw = self._handler(request)
        elif self._responses:
            raw = self._responses.pop(0)
        else:
            raw = "{}"
        latency = int((time.perf_counter() - started) * 1000)
        prompt_material = json.dumps(
            [{"role": m.role, "content": m.content} for m in request.messages],
            sort_keys=True,
        )
        return LLMResult(
            provider=self.name,
            model=request.model or self.model,
            status="succeeded",
            raw_text=raw,
            prompt_hash=hashlib.sha256(prompt_material.encode()).hexdigest(),
            response_hash=hashlib.sha256(raw.encode()).hexdigest(),
            input_tokens=max(1, len(prompt_material) // 4),
            output_tokens=max(1, len(raw) // 4),
            latency_ms=latency,
            prompt_version=request.prompt_version,
            input_evidence_ids=tuple(sorted(request.allowed_evidence_ids)),
            purpose=request.purpose,
            incident_id=request.incident_id,
        )


def json_response(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)
