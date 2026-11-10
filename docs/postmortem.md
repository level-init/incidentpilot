# Postmortem draft + citations (L4)

Grounded postmortems reject unsupported claims. A DRAFT may be created only
after the incident is **RESOLVED**. FINAL / CLOSED transitions are **L5**.

## Citation kinds

Each claim must include ≥1 citation resolving to the **same incident**:

| Kind | Ref forms |
| --- | --- |
| `evidence` | `EV-…` key or evidence UUID |
| `timeline` | timeline_event UUID (`TL-<uuid>` in markdown) |
| `action` | action UUID (`ACT-<uuid>`) |
| `validation_result` | validation_result UUID (`VR-<uuid>`) |

Uncited claims and unknown/cross-incident refs raise `UnsupportedClaimError`.

## Draft generation

```python
from incidentpilot_shared.domain.commands import create_postmortem_draft_command

create_postmortem_draft_command(conn, incident_id=incident_id)
# or pass explicit claims=[{"text": "…", "citations": [{"kind":"evidence","ref":"EV-…"}]}]
```

- Auto-draft builds claims from Evidence, Timeline, Action, ValidationResult
- Persists `domain.postmortem` (`DRAFT`), `cited_evidence_ids`, `provenance.claims`
- Refreshing an existing DRAFT is allowed; FINAL is immutable (L5)

## HTTP

```http
POST /incidents/{incident_id}/postmortem/draft
Authorization: Bearer local-dev
Content-Type: application/json

{}
```

| Status | Meaning |
| --- | --- |
| 201 | DRAFT created/refreshed |
| 400 | Uncited / unsupported claim |
| 409 | Incident not RESOLVED, or postmortem already FINAL |

```http
GET /incidents/{incident_id}/postmortem
Authorization: Bearer local-dev
```
