"""Autonomy config resolution Levels 1–3 (I3).

Most-specific matching row wins (non-null dimensions score higher).
Global default is Level 2 — no silent Level 3 production default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg import Connection

DEFAULT_AUTONOMY_LEVEL = 2


@dataclass(frozen=True, slots=True)
class AutonomyMatch:
    autonomy_level: int
    config_id: str | None
    service_key: str | None
    action_type: str | None
    environment: str | None
    severity: str | None
    notes: str | None
    specificity: int
    source: str  # config | default_fallback


def _specificity(
    *,
    service_key: str | None,
    action_type: str | None,
    environment: str | None,
    severity: str | None,
) -> int:
    return sum(
        1
        for v in (service_key, action_type, environment, severity)
        if v is not None and str(v).strip() != ""
    )


def resolve_autonomy_level(
    conn: Connection,
    *,
    service_key: str | None = None,
    action_type: str | None = None,
    environment: str | None = None,
    severity: str | None = None,
) -> AutonomyMatch:
    """Resolve autonomy level for EvaluatePolicy inputs."""
    svc = (service_key or "").strip() or None
    atype = (action_type or "").strip() or None
    env = (environment or "").strip() or None
    sev = (severity or "").strip() or None

    sql = """
        SELECT id, service_key, action_type, environment, severity,
               autonomy_level, notes
        FROM domain.autonomy_config
        WHERE (service_key IS NULL OR service_key = %s)
          AND (action_type IS NULL OR action_type = %s)
          AND (environment IS NULL OR environment = %s)
          AND (severity IS NULL OR severity = %s)
    """
    params: list[Any] = [svc, atype, env, sev]
    best: AutonomyMatch | None = None
    with conn.cursor() as cur:
        cur.execute(sql, params)
        for row in cur.fetchall():
            row_svc = str(row[1]) if row[1] is not None else None
            row_atype = str(row[2]) if row[2] is not None else None
            row_env = str(row[3]) if row[3] is not None else None
            row_sev = str(row[4]) if row[4] is not None else None
            spec = _specificity(
                service_key=row_svc,
                action_type=row_atype,
                environment=row_env,
                severity=row_sev,
            )
            candidate = AutonomyMatch(
                autonomy_level=int(row[5]),
                config_id=str(row[0]),
                service_key=row_svc,
                action_type=row_atype,
                environment=row_env,
                severity=row_sev,
                notes=str(row[6]) if row[6] is not None else None,
                specificity=spec,
                source="config",
            )
            if best is None or candidate.specificity > best.specificity:
                best = candidate
            elif (
                best is not None
                and candidate.specificity == best.specificity
                and candidate.autonomy_level < best.autonomy_level
            ):
                # Tie-break: prefer the more restrictive (lower) level.
                best = candidate

    if best is not None:
        return best
    return AutonomyMatch(
        autonomy_level=DEFAULT_AUTONOMY_LEVEL,
        config_id=None,
        service_key=None,
        action_type=None,
        environment=None,
        severity=None,
        notes="hardcoded fallback Level 2 (no autonomy_config rows matched)",
        specificity=0,
        source="default_fallback",
    )
