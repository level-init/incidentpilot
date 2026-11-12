# Postmortem draft + FINAL (L4–L5)

Grounded postmortems reject unsupported claims. A DRAFT may be created only
after the incident is **RESOLVED**. Terminal path:

`RESOLVED → (DRAFT) → FINAL + POSTMORTEM → CLOSED`

CLOSED is refused unless the postmortem is **FINAL** (L5).

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

## Web UI (M9)

Incident detail shows a **Postmortem** panel: Viewers read; Responders/Admins
create drafts and finalize. See [web.md](web.md).

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

## Finalize + CLOSED (L5)

```python
from incidentpilot_shared.domain.commands import finalize_postmortem_command

finalize_postmortem_command(
    conn,
    incident_id=incident_id,
    corrective_actions=[
        {"title": "Add deploy canary", "owner": "platform"},
    ],
)
```

- Requires existing **DRAFT**; sets **FINAL** + `corrective_actions[]` (each needs `title`)
- If incident is still RESOLVED → transitions to **POSTMORTEM**
- `POSTMORTEM → CLOSED` via `transition_incident_command` only when status is FINAL
- `RESOLVED → CLOSED` remains an illegal edge (must pass POSTMORTEM)

```http
POST /incidents/{incident_id}/postmortem/finalize
Authorization: Bearer local-dev
Content-Type: application/json

{"corrective_actions":[{"title":"Add deploy canary","owner":"platform"}]}
```

| Status | Meaning |
| --- | --- |
| 200 | FINAL; incident may be POSTMORTEM |
| 400 | Empty / invalid corrective_actions |
| 409 | Not ready, or already FINAL |

## Export package (L6)

Archive/demo artifact with **timeline**, **Evidence refs**, and **postmortem body**.
Canonical data stays in Postgres; S3 (`S3_BUCKET_POSTMORTEM_EXPORTS`) is a
best-effort snapshot (FINAL rows are immutable, so export URI is not rewritten
onto the postmortem row).

```python
from incidentpilot_shared.domain.commands import export_postmortem_package_command

result = export_postmortem_package_command(conn, incident_id=incident_id)
assert "timeline" in result.package
assert "evidence_refs" in result.package
assert result.package["postmortem"]["body_markdown"]
```

```http
GET /incidents/{incident_id}/postmortem/export
Authorization: Bearer local-dev
```

Requires FINAL; returns `{ package, export_uri?, blob_status }`.
