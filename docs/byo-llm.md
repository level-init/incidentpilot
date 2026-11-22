# Bring your own LLM (Gemini) — Q7 / #299

Clone and CI default to **`LLM_PROVIDER=fake`** — no API key, no Google bill.
For live investigation reasoning on a **self-hosted** instance, use **your**
Google Gemini key. IncidentPilot never ships a shared project key.

## Defaults (no key)

```bash
# .env — already the clone default
LLM_PROVIDER=fake
LLM_MODEL=fake-test
```

Quickstart works end-to-end with fake. Leave it until you want real model output.

## Enable Gemini (your key only)

1. Get an API key from Google AI Studio (your account).  
2. Put it in **local** `.env` — never commit; `.env` is gitignored.  
3. Restart the **general** worker only.

```bash
# .env
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
LLM_API_KEY=your-key-here
# equivalent: GEMINI_API_KEY=your-key-here
```

```bash
# general worker picks up env on start
PYTHONPATH=worker:shared:adapters \
  .venv/bin/python -m incidentpilot_worker
```

Provider details and provenance: [llm.md](llm.md). Timed path:
[quickstart.md](quickstart.md#6-optional-your-gemini-key-q7).

## Privilege split (required)

| Process | LLM key? |
| --- | --- |
| `incidentpilot-worker` (general) | **Yes** — reasoning only |
| evidence-worker | **No** |
| remediation-worker | **No** |
| api | **No** (HTTP only) |
| `incidentpilot_worker notify` | **No** Slack token here, not Gemini |

Do not inject `LLM_API_KEY` into evidence/remediation containers.

## Security

- Key stays on the machine that runs the general worker  
- No Gemini secret in GitHub Actions unless you add an explicit live-LLM job later  
- Hosted demos / story site must **not** embed your key  
- Rotating the key = edit `.env` + restart general worker  

## Verify

```bash
# With fake (default) — no network LLM calls
grep LLM_PROVIDER .env   # expect fake unless you changed it

# With gemini — missing key should fail fast at worker/provider resolve
LLM_PROVIDER=gemini LLM_API_KEY= .venv/bin/python -c \
  'from incidentpilot_adapters.llm.factory import resolve_llm_provider; resolve_llm_provider()'
# expect RuntimeError mentioning LLM_API_KEY
```

## Related

| Doc | Role |
| --- | --- |
| [llm.md](llm.md) | Providers, provenance, tool broker |
| [quickstart.md](quickstart.md) | Optional Gemini step in first-run path |
| [connect-your-stack.md](connect-your-stack.md) | Env cheat sheet includes LLM vars |
| `.env.example` | Commented gemini block |
