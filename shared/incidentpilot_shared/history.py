"""Historical incident/postmortem retrieval — suggestions only (H9).

Past incidents may suggest hypotheses/runbooks but are **not** current facts.
Hits are marked non-authoritative and must never be cited as Evidence (EV-…).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

HISTORICAL_SUGGESTION_PREFIX = "HIST-"

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass(frozen=True, slots=True)
class HistoricalHit:
    suggestion_id: str
    incident_id: UUID
    public_id: str
    title: str
    state: str
    rank: float
    postmortem_title: str | None = None
    snippet: str | None = None
    # Contract: never True — historical assist is not Evidence.
    authoritative: bool = False
    may_cite_as_evidence: bool = False


def suggestion_id_for(public_id: str) -> str:
    return f"{HISTORICAL_SUGGESTION_PREFIX}{public_id}"


def is_historical_suggestion_ref(ref: str) -> bool:
    text = str(ref).strip()
    return text.upper().startswith(HISTORICAL_SUGGESTION_PREFIX)


def retrieve_historical_assist(
    conn: Connection,
    *,
    query: str,
    limit: int = 5,
    exclude_incident_id: UUID | None = None,
) -> list[HistoricalHit]:
    """Rank past incidents / FINAL postmortems by ILIKE match (suggest only)."""
    q = (query or "").strip()
    lim = max(1, min(int(limit), 20))
    like = f"%{q}%" if q else "%"

    sql = """
        SELECT
            i.id,
            i.public_id,
            i.title,
            i.state,
            p.title AS postmortem_title,
            CASE
                WHEN p.body_markdown IS NOT NULL AND length(p.body_markdown) > 0
                THEN left(p.body_markdown, 240)
                ELSE i.summary
            END AS snippet,
            (
                CASE
                    WHEN %s = '' THEN 0.1
                    WHEN lower(i.public_id) = lower(%s) THEN 2.0
                    WHEN position(lower(%s) in lower(i.title)) > 0 THEN 1.0
                    WHEN p.title IS NOT NULL
                         AND position(lower(%s) in lower(p.title)) > 0 THEN 0.9
                    WHEN p.body_markdown IS NOT NULL
                         AND position(lower(%s) in lower(p.body_markdown)) > 0 THEN 0.6
                    WHEN i.summary IS NOT NULL
                         AND position(lower(%s) in lower(i.summary)) > 0 THEN 0.5
                    ELSE 0.2
                END
            ) AS rank_score
        FROM domain.incident i
        LEFT JOIN domain.postmortem p
            ON p.incident_id = i.id AND p.status = 'FINAL'
        WHERE (
                i.state IN ('RESOLVED', 'CLOSED', 'POSTMORTEM')
                OR p.id IS NOT NULL
              )
          AND (%s::uuid IS NULL OR i.id <> %s::uuid)
          AND (
                %s = ''
                OR i.public_id ILIKE %s
                OR i.title ILIKE %s
                OR coalesce(i.summary, '') ILIKE %s
                OR coalesce(p.title, '') ILIKE %s
                OR coalesce(p.body_markdown, '') ILIKE %s
              )
        ORDER BY rank_score DESC, i.opened_at DESC
        LIMIT %s
    """
    exclude = str(exclude_incident_id) if exclude_incident_id else None
    params: list[Any] = [
        q,
        q,
        q,
        q,
        q,
        q,
        exclude,
        exclude,
        q,
        like,
        like,
        like,
        like,
        like,
        lim,
    ]
    hits: list[HistoricalHit] = []
    with conn.cursor() as cur:
        cur.execute(sql, params)
        for row in cur.fetchall():
            public_id = str(row[1])
            hits.append(
                HistoricalHit(
                    suggestion_id=suggestion_id_for(public_id),
                    incident_id=UUID(str(row[0])),
                    public_id=public_id,
                    title=str(row[2]),
                    state=str(row[3]),
                    postmortem_title=str(row[4]) if row[4] is not None else None,
                    snippet=str(row[5]) if row[5] is not None else None,
                    rank=float(row[6] or 0.0),
                    authoritative=False,
                    may_cite_as_evidence=False,
                )
            )
    return hits


def historical_searcher_for_broker(conn: Connection):
    """Adapter for ``AiToolBroker(historical_searcher=…)`` — suggestions only."""

    def _search(args: dict[str, Any]) -> dict[str, Any]:
        exclude_raw = args.get("exclude_incident_id") or args.get("incident_id")
        exclude: UUID | None = None
        if exclude_raw:
            exclude = UUID(str(exclude_raw))
        hits = retrieve_historical_assist(
            conn,
            query=str(args.get("query") or ""),
            limit=int(args.get("limit") or 5),
            exclude_incident_id=exclude,
        )
        return {
            "query": args.get("query"),
            "authoritative": False,
            "may_cite_as_evidence": False,
            "disclaimer": (
                "Historical hits are suggestions only — not Evidence. "
                "Cite EV-… from the current incident after new collection."
            ),
            "hits": [
                {
                    "suggestion_id": h.suggestion_id,
                    "incident_id": str(h.incident_id),
                    "public_id": h.public_id,
                    "title": h.title,
                    "state": h.state,
                    "postmortem_title": h.postmortem_title,
                    "snippet": h.snippet,
                    "rank": h.rank,
                    "authoritative": False,
                    "may_cite_as_evidence": False,
                }
                for h in hits
            ],
        }

    return _search
