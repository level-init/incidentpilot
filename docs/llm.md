# LLM provider, provenance, and AI tool broker (H1–H3)

Provider-agnostic structured completions for investigation reasoning, with a
minimum provenance row on every call and a capability-scoped tool broker.

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

## AI tool broker (H3)

```python
from incidentpilot_shared import AiToolBroker, ToolScope

broker = AiToolBroker(
    scope=ToolScope(incident_id=str(incident_id), environment="local"),
    conn=conn,  # evidence_projection_read only
    collector_trigger=my_starter,  # schedules G7 collect; no Prom/Loki/Tempo
)

broker.invoke("POLICY_EVAL", {...})   # ToolDeniedError
broker.invoke("ACTION_EXECUTE", {...})  # ToolDeniedError
broker.invoke("collector_trigger", {"incident_id": ..., "collector": "logs", "query": "…"})
broker.invoke("telemetry_read", {"incident_id": ..., "query": "up", "window_seconds": 60})
```

| Rule | Behavior |
| --- | --- |
| Capabilities | `READ` / `PROPOSE` / `COLLECTOR_TRIGGER` only |
| Deny | `POLICY_EVAL`, `ACTION_EXECUTE`, GT, shell/kubectl/sql/secrets, Evidence writes |
| Evidence | `evidence_projection_read` → redacted projections only (G2) |
| Telemetry | exploratory; not Evidence authorship; no source creds on general |
| Collect | `collector_trigger` schedules evidence-worker job (G7) |
| Scope | server-bound `ToolScope` (C6); model args cannot widen incident/env |

## Hypothesis propose / rank (H4)

AI may **propose** via the broker / structured LLM output. **SYSTEM** persists rows:

```python
from incidentpilot_shared import propose_hypothesis_command, rank_hypotheses_command

propose_hypothesis_command(
    conn,
    incident_id=incident_id,
    statement="bad deploy on payment",
    cited_evidence_ids=["EV-…"],  # missing ids rejected
    heuristic_score=0.7,          # labeled score_kind=heuristic — not a probability
    proposed_by="AI",
)
```

- Multiple `PROPOSED` (OPEN) hypotheses per incident are allowed
- Missing / cross-incident EV citations → `MissingEvidenceCitationError` (no row)
- `rank_hypotheses_command` sets ranks only; CONFIRM / CAUSED_BY via `confirm_hypothesis_command` (H10)
- Broker `hypothesis_propose` stays `executed=False` — it does not INSERT

## SYSTEM LEADING + DIAGNOSED gate (H5)

```python
from incidentpilot_shared import diagnose_incident_command

diagnose_incident_command(
    conn,
    incident_id=incident_id,
    hypothesis_id=hypothesis_id,  # must be PROPOSED with citations
    expected_revision=revision,
    actor="system",  # or incident-workflow; AI sandbox denied
)
```

- Persists `status=LEADING` + `leading_at`
- Transitions incident to `DIAGNOSED` (revision bump + timeline/outbox)
- Free-form `transition_incident_command(..., DIAGNOSED)` is rejected
- Temporal activity: `apply_diagnosed_gate` on the general worker

## Runbook store + retrieval (H6)

Executable authority is **`allowed_action_types`** on a published `RunbookVersion`.
`body_markdown` is human context only.

```python
from incidentpilot_shared import retrieve_runbooks, pin_runbook_version_command

hits = retrieve_runbooks(conn, query="checkout high_error_rate", hypothesis_class="high_error_rate")
pin_runbook_version_command(conn, incident_id=…, runbook_version_id=hits[0].version_id)
```

- Seed: `checkout.high_error_rate` allows `ROLLBACK_DEPLOYMENT`
- Pin emits `RUNBOOK_FACT` via producer `runbook_store`
- Hybrid retrieval = metadata filters + Postgres FTS (pgvector deferred)

## Impact + SLO burn (H7)

```python
from incidentpilot_shared.domain.commands import (
    compute_impact_snapshot_command,
    compute_slo_burn_command,
)

compute_impact_snapshot_command(conn, incident_id=…)
compute_slo_burn_command(conn, incident_id=…)
```

- Calculators are deterministic heuristics (`impact_from_metrics.v1`, `slo_burn_from_metrics.v1`)
- Affected-user / revenue figures are **ranges labeled heuristic** — not a ledger
- Rows cite METRIC Evidence via `provenance`; query via
  `GET /incidents/{id}/impact-snapshots` and `…/slo-burns`

## Severity updater (H8)

```python
from incidentpilot_shared.domain.commands import update_incident_severity_command

update_incident_severity_command(conn, incident_id=…, actor="system")
```

- Deterministic rules (`severity_from_signals.v1`) from alert hint + impact + SLO + service criticality
- AI may explain only — `set_severity` / `update_severity` tools are denied; AI actors raise `SeverityActorDenied`
- HTTP: `POST /incidents/{id}/severity/update` (always runs as SYSTEM)

## Historical retrieval assist (H9)

```python
from incidentpilot_shared import retrieve_historical_assist

hits = retrieve_historical_assist(conn, query="checkout error rate")
# hits[*].suggestion_id like HIST-INC-… — never cite as Evidence
```

- Past RESOLVED/CLOSED/POSTMORTEM incidents + FINAL postmortems → suggestions only
- API: `GET /history/search` returns `authoritative=false` / `may_cite_as_evidence=false`
- AI tool `historical_search` (READ) carries the same disclaimer
- Citing `HIST-…` in `propose_hypothesis_command` raises `MissingEvidenceCitationError`

## EvaluatePolicy (I2) + Autonomy config (I3)

```python
from incidentpilot_shared.domain.commands import evaluate_policy_command

# Omits autonomy_level → resolves from domain.autonomy_config
evaluate_policy_command(conn, action_id=…, actor="system")
```

- SYSTEM-only; AI `POLICY_EVAL` tool remains denied; AI actors raise `PolicyActorDenied`
- `BLOCK` is absolute (no emergency override); `assert_not_blocked` gates execute paths
- HTTP: `POST /actions/{id}/policy/evaluate` (always runs as SYSTEM)
- **I7:** Admin publishes versions via `POST /policies/{key}/versions` (`ADMIN_CONFIG`);
  EvaluatePolicy stamps the **active** `policy_version` onto new PolicyDecision rows;
  past decisions and `policy_definition` rows stay immutable
- **First scored bad-deploy** (`checkout` + `ROLLBACK_DEPLOYMENT` + `local`) is **Level 2 → REQUIRE_APPROVAL**
- Level 3 is configurable via `PUT /autonomy-config` — **not** a production default
- Global default row is Level 2
- `REQUIRE_APPROVAL` auto-creates a PENDING Approval and sets action `AWAITING_APPROVAL` (I4)

## Approval create/consume (I4)

```python
from incidentpilot_shared.domain.commands import (
    decide_approval_command,
    consume_approval_command,
    assert_approval_authorizes,
)

decide_approval_command(conn, action_id=…, action_version=1, status="APPROVED", decided_by="…")
consume_approval_command(conn, action_id=…, action_version=1)
assert_approval_authorizes(conn, action_id=…, action_version=1)
```

- Bound to exact `action_version` — v2 approval cannot authorize v3 (`STALE_ACTION_VERSION`)
- Duplicate create / duplicate approve / re-consume are safe no-ops
- Reject is visible: approval `REJECTED`, action `CANCELLED`
- HTTP decide: `POST /approvals/{id}/decide` (session actor; BLOCK still un-overridable)
- Decide enqueues outbox `approval.decided` → workflow signal `approval_decision` (I5)
- Workflow `wait_for_approval`: durable `approval_timeout`; **timeout never executes** remediation (expires + replan to `DIAGNOSED`)
- **I6 harness** (no Slack): `POST /eval/approvals/{id}/decide` with `local-dev-evaluator`
  writes real Approval rows + signals the wait; reject → replan `DIAGNOSED`
  CLI: `python scripts/approval_harness.py approve|reject <approval_id>`

## VerifyExecutionAttempt (J1)

```python
from incidentpilot_shared.remediation_verify import verify_execution_attempt
from incidentpilot_adapters.remediation import execute_verified, NoopRemediationAdapter

verified = verify_execution_attempt(conn, attempt_id=…, parameters={…})  # must match SoR
execute_verified(NoopRemediationAdapter(), verified)
```

- Real `attempt_id` with **bogus params** → `ParamMismatchError`
- Adapter execute without verify → `UnverifiedExecutionError`
- Params always taken from immutable `action_version` after verify
- remediation-worker entry: `incidentpilot_remediation.execute.verify_and_execute`

## ROLLBACK_DEPLOYMENT + reconcile (J2)

```python
from incidentpilot_adapters.remediation import SimDeploymentWorld, SimRollbackAdapter
from incidentpilot_remediation.execute import verify_reconcile_and_execute

world = SimDeploymentWorld()
world.seed("checkout", "bad")
adapter = SimRollbackAdapter(world)
verified, result = verify_reconcile_and_execute(
    conn, adapter, attempt_id=…, parameters={"revision": "prev", "deployment": "checkout"}
)
# result.reconciliation_state ∈ {NOT_APPLIED, APPLIED, PARTIAL, UNKNOWN}
```

- Rollback clears bad revision (`observed → parameters.revision`)
- Retry after lost ACK: reconcile → `APPLIED` → **skip execute** (no double-apply)
- `UNKNOWN` / `PARTIAL` → `BlindRetryForbidden` (no blind full retry)
- Params: `deployment` + `revision` (SoR); sim only — K8s RBAC is J11

## RESTART_WORKLOAD + SCALE_WORKLOAD (J3)

```python
from incidentpilot_adapters.remediation import (
    SimWorkloadWorld, SimRestartAdapter, SimScaleAdapter,
)
from incidentpilot_remediation.execute import verify_reconcile_and_execute

world = SimWorkloadWorld()
world.seed("checkout-api", generation=1, replicas=2)
verify_reconcile_and_execute(conn, SimRestartAdapter(world), attempt_id=…,
                              parameters={"workload": "checkout-api"})
verify_reconcile_and_execute(conn, SimScaleAdapter(world), attempt_id=…,
                              parameters={"workload": "checkout-api", "replicas": 4})
```

- Same reconcile contract as J2 (`NOT_APPLIED`/`APPLIED`/`PARTIAL`/`UNKNOWN`)
- Restart bumps generation; scale sets desired replicas; attempt_id is idempotency key
- Lost-ACK retry skips re-mutate; `UNKNOWN` → `BlindRetryForbidden`

## Feature flag + config restore (J4)

```python
from incidentpilot_adapters.remediation import (
    SimFlagConfigWorld, SimFeatureFlagAdapter, SimConfigRestoreAdapter,
)

world = SimFlagConfigWorld()
world.seed_bad_flag_fault()       # auth:strict_jwt=true
world.seed_bad_config_faults()    # jwt_skew_seconds=0, pool_size=4
SimFeatureFlagAdapter(world).execute(...)   # DISABLE_FEATURE_FLAG / RESTORE_FEATURE_FLAG
SimConfigRestoreAdapter(world).execute(...) # RESTORE_CONFIG
```

- Clears catalog-aligned sim faults (`strict_jwt`, `jwt_skew_seconds`, `pool_size`)
- Same reconcile/idempotency contract; params: `flag`/`key` + optional `service` + desired `value`

## Validation window + ValidationResult (J7) + routing (J8)

See [docs/validation.md](validation.md). Durable `validation_window` (15m default);
`checkout_recovery.v1` thresholds: error_rate ≤ **0.05**, baseline ratio &lt; **2.0**.
One `ValidationResult` per attempt; LLM explains only.
J8 routes: `RECOVERED→RESOLVED`; NO_IMPROVEMENT→`DIAGNOSED`; REGRESSION→`DEGRADED`;
no `VALIDATING→MITIGATING`.

## Policy ↔ remediation integration (J10)

Level-2 harness `APPROVED` with `IncidentWorkflowInput.execute_on_approval=True`:
reserve `execution_attempt` **before** `MITIGATING`, then
`verify_reconcile_and_execute` (sim rollback). `BLOCK` never calls the adapter.
Rollback executes once per approve path.

## Compensation Action (J9)

```python
from incidentpilot_shared.domain.commands import propose_compensation_action_command

comp = propose_compensation_action_command(
    conn, parent_action_id=…, parameters={…}
)
# comp.action_id is new; compensates_action_id → parent
# Parent Approval cannot authorize comp — EvaluatePolicy + Approval again
```

## RemediationResult → ACTION_RESULT Evidence (J6)

```python
from incidentpilot_remediation.execute import verify_reconcile_and_execute
# after successful verify/execute, SYSTEM producer writes Evidence:
# kind=ACTION_RESULT, producer=remediation_worker, provenance.layer=ACTION_OBSERVATION
# fingerprint=remediation_worker:attempt:{attempt_id} (idempotent on lost-ACK retry)
```

- Adapters return `RemediationResult` only — they never write `domain.evidence`
- Path: Result → `append_action_result_evidence_command` → Producer (not adapter SQL)

## PAUSE_CONSUMER + REROUTE_TRAFFIC (J5)

```python
from incidentpilot_adapters.remediation import (
    SimTrafficWorld, SimPauseConsumerAdapter, SimRerouteTrafficAdapter,
)

world = SimTrafficWorld()
world.seed_queue_backlog_fault()
SimPauseConsumerAdapter(world).execute(...)  # pause notification-worker
# Mid-shift weights → PARTIAL with adapter_result["observed_state"]
SimRerouteTrafficAdapter(world).reconcile(...)
```

- Reroute `PARTIAL` always includes `observed_state` (current weights); no blind full retry
- Params: pause `consumer`; reroute `service` + `weights` or `from`/`target`/`percent`

## ProposeAction (I1)

```python
from incidentpilot_shared.domain.commands import propose_action_command

propose_action_command(
    conn,
    incident_id=…,
    action_type="ROLLBACK_DEPLOYMENT",
    parameters={"revision": "prev"},
)
# param change on same action_id → new immutable action_version
```

- Requires pinned RunbookVersion; `action_type` must be ∈ `allowed_action_types`
- Invalid types (e.g. SCALE when only ROLLBACK allowed) raise `ActionTypeNotAllowed`
- HTTP: `POST /incidents/{id}/actions`
- AI `action_propose` remains propose-only — SYSTEM persists via this command

## Confirmation rules (H10)

```python
from incidentpilot_shared.domain.commands import confirm_hypothesis_command

confirm_hypothesis_command(conn, incident_id=…, hypothesis_id=…, actor="system")
```

- Class-specific rules (`confirmation_rules.v1`); deploy-class needs CHANGE + ACTION_RESULT + RECOVERED
- **RECOVERED alone never CONFIRMs**
- SYSTEM writes optional `CAUSED_BY` evidence relation; humans/AI cannot write it directly
- AI tools `confirm_hypothesis` / `write_caused_by` are denied
- HTTP: `POST /incidents/{id}/hypotheses/{hid}/confirm` (runs as SYSTEM)
