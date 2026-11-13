"""Gemini LLM provider — outbound HTTP only; no domain writes (N9).

Reads ``LLM_API_KEY`` / ``GEMINI_API_KEY``. Default model
``gemini-2.0-flash``. CI and local default remain ``LLM_PROVIDER=fake``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from incidentpilot_adapters.llm.protocol import LLMRequest, LLMResult

_DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiLLMProvider:
    """Google Gemini generateContent adapter (general worker only)."""

    name = "gemini"

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.model = (model or os.environ.get("LLM_MODEL") or _DEFAULT_MODEL).strip()
        key = (
            api_key
            or os.environ.get("LLM_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or ""
        ).strip()
        if not key:
            raise RuntimeError(
                "Gemini requires LLM_API_KEY (or GEMINI_API_KEY) on the general worker"
            )
        self._api_key = key
        self._base = (base_url or os.environ.get("LLM_BASE_URL") or _DEFAULT_BASE).rstrip("/")
        self._timeout_s = timeout_s

    def complete(self, request: LLMRequest) -> LLMResult:
        started = time.perf_counter()
        model = (request.model or self.model).strip()
        prompt_material = json.dumps(
            [{"role": m.role, "content": m.content} for m in request.messages],
            sort_keys=True,
        )
        schema_hint = ""
        if request.response_model is not None:
            try:
                schema = request.response_model.model_json_schema()
                schema_hint = (
                    "\nRespond with a single JSON object matching this schema "
                    f"(no markdown):\n{json.dumps(schema)}"
                )
            except Exception:  # noqa: BLE001 — best-effort schema hint
                schema_hint = "\nRespond with a single JSON object only."

        contents: list[dict[str, Any]] = []
        system_bits: list[str] = []
        for msg in request.messages:
            if msg.role == "system":
                system_bits.append(msg.content)
                continue
            role = "model" if msg.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg.content}]})
        if not contents:
            contents.append({"role": "user", "parts": [{"text": "Complete the task."}]})
        if schema_hint:
            contents[-1]["parts"][-1]["text"] += schema_hint

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        if system_bits:
            body["systemInstruction"] = {"parts": [{"text": "\n".join(system_bits)}]}

        url = f"{self._base}/models/{model}:generateContent?key={urllib.parse.quote(self._api_key)}"
        raw = ""
        status = "succeeded"
        err: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            raw = _extract_text(payload)
            usage = payload.get("usageMetadata") or {}
            input_tokens = usage.get("promptTokenCount")
            output_tokens = usage.get("candidatesTokenCount") or usage.get("totalTokenCount")
        except urllib.error.HTTPError as exc:
            status = "failed"
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            err = f"gemini HTTP {exc.code}: {detail}"
        except TimeoutError:
            status = "timeout"
            err = "gemini request timed out"
        except Exception as exc:  # noqa: BLE001 — map to LLMResult
            status = "failed"
            err = f"gemini error: {exc}"

        latency = int((time.perf_counter() - started) * 1000)
        return LLMResult(
            provider=self.name,
            model=model,
            status=status,  # type: ignore[arg-type]
            raw_text=raw,
            prompt_hash=hashlib.sha256(prompt_material.encode()).hexdigest(),
            response_hash=(hashlib.sha256(raw.encode()).hexdigest() if raw else None),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency,
            error_summary=err,
            prompt_version=request.prompt_version,
            input_evidence_ids=tuple(sorted(request.allowed_evidence_ids)),
            purpose=request.purpose,
            incident_id=request.incident_id,
        )


def _extract_text(payload: dict[str, Any]) -> str:
    cands = payload.get("candidates") or []
    if not cands:
        return ""
    parts = ((cands[0] or {}).get("content") or {}).get("parts") or []
    texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
    return "".join(texts).strip()
