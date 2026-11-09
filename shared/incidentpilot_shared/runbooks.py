"""Runbook retrieval — metadata + FTS hybrid (H6).

Executable authority is ``allowed_action_types`` on published versions.
``body_markdown`` is display/context only — never an allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass(frozen=True, slots=True)
class RunbookHit:
    runbook_id: UUID
    runbook_key: str
    title: str
    version_id: UUID
    version: int
    hypothesis_class: str | None
    allowed_action_types: tuple[str, ...]
    rank: float
    # Body optional for display — callers must not treat as authority.
    body_markdown: str | None = None


def retrieve_runbooks(
    conn: Connection,
    *,
    query: str,
    limit: int = 5,
    hypothesis_class: str | None = None,
    service_key: str | None = None,
    environment: str = "local",
    include_body: bool = False,
) -> list[RunbookHit]:
    """Rank published runbook versions by metadata boost + FTS (no prose allowlist)."""
    q = (query or "").strip()
    lim = max(1, min(int(limit), 20))
    body_col = "rv.body_markdown" if include_body else "NULL::text"

    sql = f"""
        SELECT
            r.id AS runbook_id,
            r.key AS runbook_key,
            r.title,
            rv.id AS version_id,
            rv.version,
            r.hypothesis_class,
            rv.allowed_action_types,
            (
                COALESCE(ts_rank(rv.search_tsv, plainto_tsquery('english', %s)), 0)
                + CASE
                    WHEN %s::text IS NOT NULL
                         AND r.hypothesis_class = %s::text THEN 1.0
                    WHEN r.hypothesis_class IS NOT NULL
                         AND position(lower(r.hypothesis_class) in lower(%s)) > 0 THEN 0.5
                    ELSE 0.0
                  END
                + CASE
                    WHEN position(lower(r.key) in lower(%s)) > 0
                      OR position(lower(r.title) in lower(%s)) > 0 THEN 0.35
                    ELSE 0.0
                  END
            ) AS rank_score,
            {body_col} AS body_markdown
        FROM domain.runbook_version rv
        JOIN domain.runbook r ON r.id = rv.runbook_id
        LEFT JOIN domain.service s ON s.id = r.service_id
        WHERE rv.status = 'published'
          AND (%s::text IS NULL OR r.hypothesis_class = %s::text)
          AND (%s::text IS NULL OR (s.key = %s::text AND s.environment = %s::text))
          AND (
                %s = ''
                OR rv.search_tsv @@ plainto_tsquery('english', %s)
                OR r.key ILIKE '%%' || %s || '%%'
                OR r.title ILIKE '%%' || %s || '%%'
                OR coalesce(r.hypothesis_class, '') ILIKE '%%' || %s || '%%'
              )
        ORDER BY rank_score DESC, r.key ASC, rv.version DESC
        LIMIT %s
    """
    params: list[Any] = [
        q,  # ts_rank
        hypothesis_class,
        hypothesis_class,
        q,  # position hypothesis in query
        q,
        q,  # key/title in query
        hypothesis_class,
        hypothesis_class,
        service_key,
        service_key,
        environment,
        q,
        q,
        q,
        q,
        q,
        lim,
    ]
    hits: list[RunbookHit] = []
    with conn.cursor() as cur:
        cur.execute(sql, params)
        for row in cur.fetchall():
            allowed = row[6] or []
            hits.append(
                RunbookHit(
                    runbook_id=UUID(str(row[0])),
                    runbook_key=str(row[1]),
                    title=str(row[2]),
                    version_id=UUID(str(row[3])),
                    version=int(row[4]),
                    hypothesis_class=str(row[5]) if row[5] is not None else None,
                    allowed_action_types=tuple(str(x) for x in allowed),
                    rank=float(row[7] or 0.0),
                    body_markdown=str(row[8]) if row[8] is not None else None,
                )
            )
    return hits


def runbook_searcher_for_broker(conn: Connection):
    """Adapter for ``AiToolBroker(runbook_searcher=…)`` — structured hits only."""

    def _search(args: dict[str, Any]) -> dict[str, Any]:
        hits = retrieve_runbooks(
            conn,
            query=str(args.get("query") or ""),
            limit=int(args.get("limit") or 5),
            include_body=False,
        )
        return {
            "query": args.get("query"),
            "hits": [
                {
                    "runbook_key": h.runbook_key,
                    "title": h.title,
                    "version_id": str(h.version_id),
                    "version": h.version,
                    "hypothesis_class": h.hypothesis_class,
                    "allowed_action_types": list(h.allowed_action_types),
                    "rank": h.rank,
                }
                for h in hits
            ],
            # Authority reminder for consumers.
            "authority": "allowed_action_types",
        }

    return _search
