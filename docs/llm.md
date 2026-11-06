# LLM provider + AIInvocation provenance (H1 / H2)

Provider-agnostic structured completions for investigation reasoning, with a
minimum provenance row on every call.

## Interface

```python
from incidentpilot_adapters.llm import (
    FakeLLMProvider,
    LLMMessage,
    LLMRequest,
)
from incidentpilot_shared import complete_structured_recorded

result, invocation = complete_structured_recorded(
    conn,
    FakeLLMProvider(responses=['{"statement":"…","cited_evidence_ids":["EV-…"],"confidence":0.5}']),
    LLMRequest(
        purpose="hypothesis_propose",
        messages=[LLMMessage(role="user", content="…")],
        response_model=MyPydanticModel,  # extra="forbid"
        allowed_evidence_ids=frozenset({"EV-…"}),
        incident_id=str(incident_id),
        prompt_version="h2.v1",
    ),
)
```

- Invalid JSON → rejected (`StructuredOutputError`) **after** a failed row is written
- Extra fields / schema violations → rejected (failed row written)
- Invented Evidence ids → rejected (failed row written)
- Adapters never call shared commands (B7); H2 persistence lives in shared

## Provenance fields (H2)

Each `domain.ai_invocation` row records at least:

| Field | Source |
| --- | --- |
| `model` | `LLMResult.model` |
| `prompt_version` | `request_metadata.prompt_version` |
| `input_evidence_ids` | `request_metadata.input_evidence_ids` |
| `status` | succeeded / failed / timeout / cancelled |
| `created_at` | DB default |
| `incident_id` | linked when provided |

Full S3 prompt packages (`artifact_uri`) are L3 / out of scope for H2.

`record_ai_invocation_command` is the B7 mutation path; workers should prefer
`complete_structured_recorded` so success and validation failure both leave a row.

## Env (general worker only)

| Variable | Role |
| --- | --- |
| `LLM_PROVIDER` | `fake` (default) — live vendors later |
| `LLM_MODEL` | model id string |
| `OPENAI_API_KEY` / `LLM_API_KEY` | reserved for vendor adapters |

Keep keys **off** evidence-worker and remediation-worker (same privilege split
as G7 inverted: reasoning on general, telemetry creds on evidence).
