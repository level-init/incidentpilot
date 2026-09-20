# IncidentPilot — Product Overview

This document is the **shared goal** for the finished system. Implementation
details may evolve; the decisions below should not be casually reopened.

## What we are building

IncidentPilot is a **safe, evidence-driven incident-response control plane**.

When a production-like alert fires, the system:

1. Creates and manages an incident  
2. Collects logs, metrics, traces, and recent changes  
3. Maintains competing, evidence-linked hypotheses  
4. Retrieves a versioned operational runbook  
5. Estimates customer / SLO impact  
6. Coordinates humans (Slack + web dashboard)  
7. Proposes remediation  
8. Executes only through **policy → optional approval → execution attempt → adapter**  
9. Validates recovery (and reconciles / compensates when needed)  
10. Writes an evidence-grounded postmortem  
11. Can be **scored** against isolated ground truth in controlled scenarios  

It is a portfolio-grade, production-style demo—not a chatbot that guesses root cause.

## Closed-loop lifecycle

```text
Fault in simulated (or demo) environment
        ↓
Telemetry changes naturally
        ↓
Alert fires (Alertmanager; CloudWatch later)
        ↓
Normalize + correlate → Incident
        ↓
DETECTED → TRIAGING → INVESTIGATING
        ↓
Evidence collection (metrics / logs / traces / changes)
        ↓
Competing Hypotheses (AI proposes; SYSTEM writes)
        ↓
DIAGNOSED → runbook pin + impact / severity
        ↓
Action proposed (e.g. ROLLBACK_DEPLOYMENT)
        ↓
PolicyDecision: ALLOW_AUTONOMOUS | REQUIRE_APPROVAL | BLOCK
        ↓
Approval if required (human / Slack / eval harness)
        ↓
Reserve execution_attempt → MITIGATING → adapter execute
        ↓
ACTION_RESULT Evidence → VALIDATING
        ↓
RECOVERED → RESOLVED
  or replan / DEGRADED + compensation (full policy again)
        ↓
Operational evaluation (scored runs) @ RESOLVED
        ↓
POSTMORTEM → CLOSED
        ↓
Postmortem evaluation (scored runs) @ CLOSED
```

## Five non-negotiables

1. **Investigate from real telemetry and change evidence** — not scenario hints.  
2. **Competing, revisable, evidence-linked hypotheses** — citations required.  
3. **Policy-gated remediation** with validation and safe undo where applicable.  
4. **Immutable timeline + audit + AI provenance**.  
5. **Reproducible scenario evaluation** with GroundTruth isolated from IncidentPilot.

## Locked design decisions

### Safety and authority

- **AI may** interpret, rank, summarize, and propose.  
- **AI may not** invent Evidence, declare causal truth alone, authorize privileged actions, or call remediation APIs.  
- **Evidence** is the factual substrate; Timeline is process chronicle; Hypothesis is interpretation.  
- Remediation path is exclusive:  
  `Action → PolicyDecision → Approval? → execution_attempt → Remediation Adapter`  
- Admin **cannot** silently override `BLOCK`.  
- First scored vertical uses **Level 2** (approval required) with an eval/test harness; Level 3 comes later.

### Autonomy levels

| Level | Behavior |
| --- | --- |
| 1 | Observe and recommend |
| 2 | Execute after approval |
| 3 | Auto-execute only when policy allows |

Configurable per service / action / environment / severity.

### Domain ≠ technology

| Concept | Implementation (v1) |
| --- | --- |
| Workflow spine | Temporal (Cloud preferred in production-demo) |
| Domain system of record | PostgreSQL |
| Vector / hybrid retrieval | pgvector + Postgres FTS |
| Evidence graph | Postgres relations (Neo4j not assumed) |
| Event-driven delivery | Transactional outbox (Kafka not required) |
| Blobs / raw refs | S3 / MinIO |
| Cache | Redis optional, never authoritative |

### Evaluation isolation

- **Scenario** defines reality (faults, traffic, deploys).  
- **GroundTruth** is the answer key — **evaluator-only** (not readable by IncidentPilot or the scenario runner during execution).  
- Faults become visible only through app → telemetry → collectors → Evidence.  
- `ScenarioRun FAILED` = evaluation invalid (infra/baseline).  
- `EVALUATED + pass=false` = environment valid, IncidentPilot wrong.

### Runtime shape (few deployables)

- `incidentpilot-api` — short-lived HTTP / webhooks  
- `incidentpilot-worker` — Temporal + reasoning (no rollback keys, no GT)  
- Evidence producer workers — collectors / deterministic processors  
- `remediation-worker` — privileged execute / reconcile only  
- `incidentpilot-web` — dashboard  
- `scenario-runner` / `evaluator` — isolated from investigation path  
- Simulation microservices + observability stack  

Agents are **capability roles** inside workers, not twelve microservices.

## Simulated world

Demo environment (not a real customer production):

```text
API Gateway → Auth, Checkout, Payment, Inventory, Notification
```

Instrumented with Prometheus, Loki, OpenTelemetry/Tempo, Grafana, Alertmanager.

**Eight scenario classes** (full product):

1. Bad application deployment  
2. Dependency timeout  
3. Database connection exhaustion  
4. Memory leak  
5. CPU / resource exhaustion  
6. Queue backlog  
7. Bad configuration / feature flag  
8. Cascading failure (origin ≠ symptom)  

**First vertical to prove the system:** bad-deployment → scored end-to-end.

## Environments

| Environment | Role |
| --- | --- |
| Local | Docker Compose profiles (`core` / `evidence` / `simulation` / `full`) |
| Test | Compose or kind/k3d |
| Staging | Small AWS EKS (same IaC path as demo) |
| Production-demo | AWS EKS, real security patterns, small capacity |

## Build order (phases, not scope cuts)

Phases are **implementation order**. The finished product still includes platform,
cloud, eval, and hardening—not a permanently reduced MVP.

1. Foundation (repo, Postgres schemas/roles, Compose, auth skeleton)  
2. Domain model + Incident state machine + Temporal spine  
3. Simulation + observability + alert ingest  
4. Evidence producers + change intelligence  
5. Investigation reasoning (hypotheses, runbooks, impact)  
6. Policy, actions, approval, remediation, validation  
7. Timeline / audit / provenance / postmortem + Slack + ops UI  
8. Scenario runner + evaluator; first scored bad-deployment  
9. Remaining scenarios, Level 3, cloud promotion, CI hardening  

## Explicitly out of scope

- Supporting every cloud / APM / CI vendor  
- Mobile, billing, multi-tenant SaaS  
- Custom LLM training / general coding agent  
- Replacing PagerDuty or a full APM  
- Kafka or Neo4j as day-one requirements  
- Building a custom workflow engine instead of Temporal  

**Deferred (not core):** emergency override of `BLOCK`, manual incident create,
GitHub Issue creation for corrective actions.

## Collaboration

Git branching and PR rules: [git-standards.md](git-standards.md).

Issue sizing will grow and shrink as we learn; treat the product overview as the
north star and break work from the **build order** and critical vertical above.
