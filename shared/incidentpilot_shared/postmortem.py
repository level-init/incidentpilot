"""Postmortem draft generation + citation validator (L4).

Grounded postmortems reject unsupported claims. Citations may reference
Evidence, TimelineEvent, Action, or ValidationResult on the same incident.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

if TYPE_CHECKING:
    from psycopg import Connection

CitationKind = Literal["evidence", "timeline", "action", "validation_result"]

_KIND_ALIASES: dict[str, CitationKind] = {
    "evidence": "evidence",
    "ev": "evidence",
    "timeline": "timeline",
    "tl": "timeline",
    "timeline_event": "timeline",
    "action": "action",
    "act": "action",
    "validation": "validation_result",
    "validation_result": "validation_result",
    "vr": "validation_result",
}

# Inline markers in markdown: [EV-…], [TL-<uuid>], [ACT-<uuid>], [VR-<uuid>]
_INLINE_CITE_RE = re.compile(
    r"\[(?P<token>(?:EV-[A-Za-z0-9]+|TL-[0-9a-fA-F-]{36}|ACT-[0-9a-fA-F-]{36}|VR-[0-9a-fA-F-]{36}|[0-9a-fA-F-]{36}))\]"
)


class UnsupportedClaimError(ValueError):
    """Raised when a postmortem claim is uncited or cites unknown/cross-incident refs."""


@dataclass(frozen=True, slots=True)
class PostmortemCitation:
    kind: CitationKind
    ref: str


@dataclass(frozen=True, slots=True)
class PostmortemClaim:
    text: str
    citations: tuple[PostmortemCitation, ...]


def normalize_citation(kind: str, ref: str) -> PostmortemCitation:
    raw_kind = str(kind).strip().lower()
    if raw_kind not in _KIND_ALIASES:
        raise UnsupportedClaimError(f"unsupported citation kind: {kind!r}")
    token = str(ref).strip()
    if not token:
        raise UnsupportedClaimError("empty citation ref")
    mapped = _KIND_ALIASES[raw_kind]
    # Allow prefixed refs; strip kind prefix for storage resolution.
    upper = token.upper()
    if mapped == "evidence" and upper.startswith("EV-"):
        return PostmortemCitation(kind="evidence", ref=token)
    if mapped == "timeline" and upper.startswith("TL-"):
        return PostmortemCitation(kind="timeline", ref=token[3:])
    if mapped == "action" and upper.startswith("ACT-"):
        return PostmortemCitation(kind="action", ref=token[4:])
    if mapped == "validation_result" and upper.startswith("VR-"):
        return PostmortemCitation(kind="validation_result", ref=token[3:])
    return PostmortemCitation(kind=mapped, ref=token)


def parse_claim_dict(raw: dict[str, Any]) -> PostmortemClaim:
    text = str(raw.get("text") or "").strip()
    if not text:
        raise UnsupportedClaimError("claim text is required")
    cites_raw = raw.get("citations") or []
    if not isinstance(cites_raw, list):
        raise UnsupportedClaimError("claim citations must be a list")
    citations: list[PostmortemCitation] = []
    for item in cites_raw:
        if isinstance(item, str):
            citations.append(_citation_from_token(item))
        elif isinstance(item, dict):
            citations.append(
                normalize_citation(
                    str(item.get("kind") or item.get("type") or ""),
                    str(item.get("ref") or item.get("id") or ""),
                )
            )
        else:
            raise UnsupportedClaimError(f"invalid citation entry: {item!r}")
    if not citations:
        raise UnsupportedClaimError(f"uncited claim rejected: {text[:120]!r}")
    return PostmortemClaim(text=text, citations=tuple(citations))


def _citation_from_token(token: str) -> PostmortemCitation:
    t = token.strip()
    upper = t.upper()
    if upper.startswith("EV-"):
        return PostmortemCitation(kind="evidence", ref=t)
    if upper.startswith("TL-"):
        return PostmortemCitation(kind="timeline", ref=t[3:])
    if upper.startswith("ACT-"):
        return PostmortemCitation(kind="action", ref=t[4:])
    if upper.startswith("VR-"):
        return PostmortemCitation(kind="validation_result", ref=t[3:])
    # Bare uuid — ambiguous; reject rather than guess.
    raise UnsupportedClaimError(
        f"citation token {token!r} needs a kind prefix (EV-/TL-/ACT-/VR-) or kind field"
    )


def extract_inline_citations(markdown: str) -> list[PostmortemCitation]:
    found: list[PostmortemCitation] = []
    seen: set[tuple[str, str]] = set()
    for match in _INLINE_CITE_RE.finditer(markdown or ""):
        cite = _citation_from_token(match.group("token"))
        key = (cite.kind, cite.ref)
        if key in seen:
            continue
        seen.add(key)
        found.append(cite)
    return found


def validate_postmortem_claims(
    conn: Connection,
    *,
    incident_id: UUID,
    claims: list[PostmortemClaim] | tuple[PostmortemClaim, ...],
) -> tuple[UUID, ...]:
    """Validate every claim has resolvable same-incident citations.

    Returns the set of Evidence UUIDs cited (for ``cited_evidence_ids``).
    Uncited claims or unknown refs raise ``UnsupportedClaimError``.
    """
    if not claims:
        raise UnsupportedClaimError("postmortem requires at least one grounded claim")

    evidence_ids: list[UUID] = []
    seen_ev: set[str] = set()

    for claim in claims:
        if not claim.citations:
            raise UnsupportedClaimError(
                f"uncited claim rejected: {claim.text[:120]!r}"
            )
        for cite in claim.citations:
            resolved = _resolve_citation(conn, incident_id=incident_id, citation=cite)
            if cite.kind == "evidence":
                key = str(resolved)
                if key not in seen_ev:
                    seen_ev.add(key)
                    evidence_ids.append(resolved)
    return tuple(evidence_ids)


def _resolve_citation(
    conn: Connection,
    *,
    incident_id: UUID,
    citation: PostmortemCitation,
) -> UUID:
    with conn.cursor() as cur:
        if citation.kind == "evidence":
            cur.execute(
                """
                SELECT id FROM domain.evidence
                WHERE incident_id = %s
                  AND (evidence_key = %s OR id::text = %s)
                LIMIT 1
                """,
                (str(incident_id), citation.ref, citation.ref),
            )
        elif citation.kind == "timeline":
            cur.execute(
                """
                SELECT id FROM domain.timeline_event
                WHERE incident_id = %s AND id::text = %s
                LIMIT 1
                """,
                (str(incident_id), citation.ref),
            )
        elif citation.kind == "action":
            cur.execute(
                """
                SELECT id FROM domain.action
                WHERE incident_id = %s AND id::text = %s
                LIMIT 1
                """,
                (str(incident_id), citation.ref),
            )
        elif citation.kind == "validation_result":
            cur.execute(
                """
                SELECT id FROM domain.validation_result
                WHERE incident_id = %s AND id::text = %s
                LIMIT 1
                """,
                (str(incident_id), citation.ref),
            )
        else:  # pragma: no cover
            raise UnsupportedClaimError(f"unsupported citation kind: {citation.kind}")
        row = cur.fetchone()
    if row is None:
        raise UnsupportedClaimError(
            f"unsupported claim citation {citation.kind}:{citation.ref} "
            f"for incident {incident_id}"
        )
    return UUID(str(row[0]))


def build_draft_claims_from_incident(
    conn: Connection,
    *,
    incident_id: UUID,
) -> list[PostmortemClaim]:
    """Deterministic draft claims grounded in SoR rows (not LLM invention)."""
    claims: list[PostmortemClaim] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT evidence_key, id, summary
            FROM domain.evidence
            WHERE incident_id = %s
            ORDER BY observed_at ASC, ingested_at ASC
            LIMIT 20
            """,
            (str(incident_id),),
        )
        for key, eid, summary in cur.fetchall():
            ref = str(key) if key else str(eid)
            claims.append(
                PostmortemClaim(
                    text=f"Observed: {summary}",
                    citations=(PostmortemCitation(kind="evidence", ref=ref),),
                )
            )

        cur.execute(
            """
            SELECT id, event_type, summary
            FROM domain.timeline_event
            WHERE incident_id = %s
            ORDER BY occurred_at ASC, created_at ASC
            LIMIT 30
            """,
            (str(incident_id),),
        )
        for tid, event_type, summary in cur.fetchall():
            claims.append(
                PostmortemClaim(
                    text=f"Process: [{event_type}] {summary}",
                    citations=(
                        PostmortemCitation(kind="timeline", ref=str(tid)),
                    ),
                )
            )

        cur.execute(
            """
            SELECT id, action_type, status
            FROM domain.action
            WHERE incident_id = %s
            ORDER BY created_at ASC
            LIMIT 20
            """,
            (str(incident_id),),
        )
        for aid, action_type, status in cur.fetchall():
            claims.append(
                PostmortemClaim(
                    text=f"Action {action_type} ended {status}",
                    citations=(PostmortemCitation(kind="action", ref=str(aid)),),
                )
            )

        cur.execute(
            """
            SELECT id, outcome
            FROM domain.validation_result
            WHERE incident_id = %s
            ORDER BY decided_at ASC NULLS LAST, id ASC
            LIMIT 20
            """,
            (str(incident_id),),
        )
        for vid, outcome in cur.fetchall():
            claims.append(
                PostmortemClaim(
                    text=f"Validation outcome {outcome}",
                    citations=(
                        PostmortemCitation(kind="validation_result", ref=str(vid)),
                    ),
                )
            )
    return claims


def render_draft_markdown(
    *,
    public_id: str,
    title: str,
    claims: list[PostmortemClaim] | tuple[PostmortemClaim, ...],
) -> str:
    lines = [
        f"# Postmortem draft — {public_id}",
        "",
        f"**Incident:** {title}",
        "",
        "## Grounded claims",
        "",
    ]
    for i, claim in enumerate(claims, start=1):
        markers: list[str] = []
        for cite in claim.citations:
            if cite.kind == "evidence":
                markers.append(f"[{cite.ref}]")
            elif cite.kind == "timeline":
                markers.append(f"[TL-{cite.ref}]")
            elif cite.kind == "action":
                markers.append(f"[ACT-{cite.ref}]")
            else:
                markers.append(f"[VR-{cite.ref}]")
        lines.append(f"{i}. {claim.text} {' '.join(markers)}")
    lines.append("")
    return "\n".join(lines)


def claims_to_json(
    claims: list[PostmortemClaim] | tuple[PostmortemClaim, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "text": c.text,
            "citations": [{"kind": x.kind, "ref": x.ref} for x in c.citations],
        }
        for c in claims
    ]
