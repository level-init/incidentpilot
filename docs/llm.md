# LLM provider abstraction (H1)

Provider-agnostic structured completions for investigation reasoning.

## Interface

```python
from incidentpilot_adapters.llm import (
    FakeLLMProvider,
    LLMMessage,
    LLMRequest,
    complete_structured,
)

result = complete_structured(
    FakeLLMProvider(responses=['{"statement":"…","cited_evidence_ids":["EV-…"],"confidence":0.5}']),
    LLMRequest(
        purpose="hypothesis_propose",
        messages=[LLMMessage(role="user", content="…")],
        response_model=MyPydanticModel,  # extra="forbid"
        allowed_evidence_ids=frozenset({"EV-…"}),
    ),
)
```

- Invalid JSON → rejected (`StructuredOutputError`)
- Extra fields / schema violations → rejected
- Invented Evidence ids → rejected
- **No** domain mutation from prose (adapters never call shared commands)

`LLMResult` fields align with `domain.ai_invocation` for H2 persistence
(`provider`, `model`, `status`, hashes, tokens, `error_summary`).

## Env (general worker only)

| Variable | Role |
| --- | --- |
| `LLM_PROVIDER` | `fake` (default) — live vendors later |
| `LLM_MODEL` | model id string |
| `OPENAI_API_KEY` / `LLM_API_KEY` | reserved for vendor adapters |

Keep keys **off** evidence-worker and remediation-worker (same privilege split
as G7 inverted: reasoning on general, telemetry creds on evidence).
