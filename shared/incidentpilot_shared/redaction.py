"""Redaction service — LLM projections only; never rewrite canonical Evidence (C4).

Canonical Evidence (`payload` / structured_data) is append-only and must remain
intact. AI / LLM consumers receive a deep-copied projection with secrets and
PII replaced. Fail closed: any redaction failure raises ``RedactionError`` so
callers must not supply the payload to an LLM.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any


class RedactionError(Exception):
    """Raised when redaction fails or residual secrets remain (fail closed)."""


@dataclass(frozen=True, slots=True)
class RedactionRule:
    name: str
    pattern: re.Pattern[str]
    replacement: str


def _rule(name: str, pattern: str, flags: int = 0) -> RedactionRule:
    return RedactionRule(
        name=name,
        pattern=re.compile(pattern, flags),
        replacement=f"[REDACTED:{name}]",
    )


# Ordered rules: more specific first. Keep replacements stable for tests.
_DEFAULT_RULES: tuple[RedactionRule, ...] = (
    _rule(
        "private_key",
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    ),
    _rule("aws_access_key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    _rule(
        "aws_secret_key",
        r"(?i)(aws[_-]?secret[_-]?access[_-]?key|secret[_-]?access[_-]?key)"
        r"\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?",
    ),
    _rule("github_token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b"),
    _rule("github_pat", r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    _rule("slack_token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    _rule(
        "jwt",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    ),
    _rule(
        "bearer_token",
        r"(?i)(authorization\s*[=:]\s*)?bearer\s+[A-Za-z0-9._\-+=/]{20,}",
    ),
    _rule(
        "connection_password",
        r"(?i)\b((?:postgres|postgresql|mysql|mongodb|redis|amqp)(?:\+\w+)?://"
        r"[^:/\s]+):([^@/\s]+)@",
    ),
    _rule(
        "secret_assignment",
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
        r"password|passwd|secret|token)\s*[=:]\s*['\"]?([^\s'\"]{8,})['\"]?",
    ),
    _rule(
        "email",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    ),
)


@dataclass(frozen=True, slots=True)
class EvidenceProjection:
    """Redacted view safe for LLM supply. Canonical Evidence is never this object."""

    summary: str
    structured_data: dict[str, Any]
    redacted_fields: tuple[str, ...]


def _apply_rules(text: str, rules: tuple[RedactionRule, ...]) -> tuple[str, list[str]]:
    hit: list[str] = []
    out = text
    for rule in rules:
        updated, n = rule.pattern.subn(rule.replacement, out)
        if n:
            hit.append(rule.name)
            out = updated
    return out, hit


def _redact_value(
    value: Any,
    rules: tuple[RedactionRule, ...],
    path: str,
    hits: list[str],
) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        redacted, names = _apply_rules(value, rules)
        for name in names:
            hits.append(f"{path}:{name}" if path else name)
        return redacted
    if isinstance(value, dict):
        return {
            str(k): _redact_value(v, rules, f"{path}.{k}" if path else str(k), hits)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, rules, f"{path}[{i}]", hits) for i, item in enumerate(value)]
    if isinstance(value, tuple):
        return tuple(
            _redact_value(item, rules, f"{path}[{i}]", hits) for i, item in enumerate(value)
        )
    # Unknown types must not leak into LLM supply.
    raise RedactionError(f"unsupported value type at {path or '<root>'}: {type(value).__name__}")


def _residual_secret_scan(text: str) -> str | None:
    """Cheap post-pass: if high-confidence secret shapes remain, fail closed."""
    probes = (
        (r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "aws_access_key"),
        (r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b", "github_token"),
        (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "slack_token"),
        (r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", "private_key"),
        (
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
            "jwt",
        ),
    )
    for pattern, name in probes:
        if re.search(pattern, text):
            return name
    return None


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for v in value.values():
            out.extend(_walk_strings(v))
        return out
    if isinstance(value, list | tuple):
        out = []
        for item in value:
            out.extend(_walk_strings(item))
        return out
    return []


def project_evidence_for_llm(
    *,
    summary: str,
    structured_data: dict[str, Any],
    rules: tuple[RedactionRule, ...] | None = None,
) -> EvidenceProjection:
    """Return a redacted projection. Never mutates ``structured_data``.

    Raises ``RedactionError`` on failure — callers must not send the payload
    to an LLM when this raises (fail closed).
    """
    if not isinstance(structured_data, dict):
        raise RedactionError("structured_data must be a dict")

    active = rules if rules is not None else _DEFAULT_RULES
    hits: list[str] = []

    try:
        # Deep copy first so canonical Evidence stays untouched even if we crash.
        working = copy.deepcopy(structured_data)
        redacted_summary, summary_hits = _apply_rules(summary, active)
        hits.extend(summary_hits)
        redacted_data = _redact_value(working, active, "", hits)
        if not isinstance(redacted_data, dict):
            raise RedactionError("projection structured_data must remain a dict")
    except RedactionError:
        raise
    except Exception as exc:  # noqa: BLE001 — fail closed for any redaction fault
        raise RedactionError(f"redaction failed: {exc}") from exc

    for text in [redacted_summary, *_walk_strings(redacted_data)]:
        residual = _residual_secret_scan(text)
        if residual is not None:
            raise RedactionError(f"residual secret after redaction: {residual}")

    # Deduplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            ordered.append(h)

    return EvidenceProjection(
        summary=redacted_summary,
        structured_data=redacted_data,
        redacted_fields=tuple(ordered),
    )


def supply_projection_to_llm(
    *,
    summary: str,
    structured_data: dict[str, Any],
    rules: tuple[RedactionRule, ...] | None = None,
) -> EvidenceProjection:
    """Fail-closed gate for LLM supply — alias of ``project_evidence_for_llm``.

    Callers must catch ``RedactionError`` and refuse to invoke the model.
    """
    return project_evidence_for_llm(
        summary=summary,
        structured_data=structured_data,
        rules=rules,
    )
