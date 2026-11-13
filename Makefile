# IncidentPilot local quality gates (A3 / #2).
# Prefer: make bootstrap && make lint && make test

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip
RUFF := $(BIN)/ruff
MYPY := $(BIN)/mypy
PYTEST := $(BIN)/pytest

PY_SRC := api worker remediation_worker shared adapters scenario_runner evaluator simulation

COMPOSE ?= docker compose
PROFILE ?= core
DURATION ?= 60
RPS ?= 1

.PHONY: bootstrap lint format typecheck test help \
	compose-core compose-full compose-up compose-down compose-ps compose-config \
	migrate db-verify-isolation verify-local-infra openapi-export api-run web-dev \
	temporal-queue-smoke test-temporal-d6 sim-happy-path sim-contract-scan test-sim-contract \
	test-isolation isolation-scan \
	obs-smoke sim-traffic sim-baseline-gate sim-inject \
	scenario-list scenario-run scenario-reset scenario eval

help:
	@echo "Targets:"
	@echo "  make bootstrap             - create .venv and install requirements + dev tools"
	@echo "  make lint                  - ruff check + format check + mypy"
	@echo "  make format                - ruff format (writes files)"
	@echo "  make typecheck             - mypy only"
	@echo "  make test                  - pytest (scaffold smoke tests)"
	@echo "  make compose-core          - docker compose --profile core up -d"
	@echo "  make compose-full          - docker compose --profile full up -d"
	@echo "  make compose-up PROFILE=…  - evidence|simulation|redis|core|full"
	@echo "  make compose-down          - stop all compose profiles"
	@echo "  make compose-ps            - list compose services"
	@echo "  make compose-config        - validate compose for PROFILE (default core)"
	@echo "  make migrate               - apply deploy/db/migrations"
	@echo "  make db-verify-isolation   - prove GT denied for ip_app/ip_runner; no app DDL"
	@echo "  make verify-local-infra    - Temporal UI + local S3 put/get smoke"
	@echo "  make temporal-queue-smoke  - workers subscribe to general/evidence/remediation"
	@echo "  make test-temporal-d6      - D6 five-test Temporal regression (needs Postgres)"
	@echo "  make sim-happy-path        - curl checkout happy path via sim-gateway :8100"
	@echo "  make sim-contract-scan     - fail if sim exposes GT / root-cause cheat routes"
	@echo "  make test-sim-contract     - pytest contract suite + sim_contract_scan (E6/CI)"
	@echo "  make test-isolation        - N8 isolation-integrity suite (required for scored runs)"
	@echo "  make isolation-scan        - static GT-leak scan of investigation path"
	@echo "  make sim-baseline-gate     - curl all /healthz + gateway /readyz (E4)"
	@echo "  make sim-traffic           - baseline load (DURATION=60 RPS=1)"
	@echo "  make sim-inject ARGS='…'   - fault injectors (list|activate|reset|status)"
	@echo "  make scenario-list         - list scenarios.scenario catalog (N1)"
	@echo "  make scenario-run ARGS='…' - run scenario (baseline→inject; FAILED if dirty)"
	@echo "  make scenario-reset        - clear faults; keep ScenarioRun history"
	@echo "  make scenario NAME=…       - N9 scored vertical (Level 2 harness; CLI NAME= only)"
	@echo "  make eval                  - N9 pin dual-stage eval for last scenario"
	@echo "  make obs-smoke             - Prom/Loki/Tempo/Grafana/AM health (evidence profile)"
	@echo "  make openapi-export        - write openapi/openapi.json"
	@echo "  make api-run               - run FastAPI on :8000"
	@echo "  make web-dev               - Next.js dashboard on :3000 (M1)"

bootstrap:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt -r simulation/requirements.txt

lint: $(VENV)
	$(RUFF) check $(PY_SRC) tests
	$(RUFF) format --check $(PY_SRC) tests
	$(MYPY)

format: $(VENV)
	$(RUFF) check --fix $(PY_SRC) tests
	$(RUFF) format $(PY_SRC) tests

typecheck: $(VENV)
	$(MYPY)

test: $(VENV)
	$(PYTEST)

compose-core:
	$(COMPOSE) --profile core up -d

compose-full:
	$(COMPOSE) --profile full up -d

compose-up:
	$(COMPOSE) --profile $(PROFILE) up -d

compose-down:
	$(COMPOSE) --profile core --profile redis --profile evidence --profile simulation --profile full down

compose-ps:
	$(COMPOSE) --profile core --profile redis --profile evidence --profile simulation --profile full ps

compose-config:
	$(COMPOSE) --profile $(PROFILE) config >/dev/null
	@echo "compose config OK for profile=$(PROFILE)"

migrate:
	./scripts/db_migrate.sh

db-verify-isolation:
	./scripts/db_verify_isolation.sh

verify-local-infra:
	./scripts/verify_local_infra.sh

temporal-queue-smoke: $(VENV)
	PYTHONPATH="$(CURDIR)/worker:$(CURDIR)/shared:$$PYTHONPATH" \
		$(BIN)/python -m incidentpilot_worker smoke
	PYTHONPATH="$(CURDIR)/worker:$(CURDIR)/shared:$$PYTHONPATH" \
		$(BIN)/python -m incidentpilot_worker evidence smoke
	PYTHONPATH="$(CURDIR)/remediation_worker:$(CURDIR)/shared:$$PYTHONPATH" \
		$(BIN)/python -m incidentpilot_remediation smoke

# D6: approval wait+kill, validation single result, reconcile no-dup,
# stale revision non-retryable, BEST_EFFORT Slack failure leaves domain intact.
test-temporal-d6: $(VENV)
	$(PYTEST) -m temporal_d6 -v --override-ini="addopts="

sim-happy-path:
	./scripts/sim_happy_path.sh

sim-contract-scan: $(VENV)
	$(BIN)/python scripts/sim_contract_scan.py

test-sim-contract: $(VENV)
	$(PYTEST) tests/test_sim_contract.py tests/test_sim_services.py -k "contract or forbidden" -q
	$(BIN)/python scripts/sim_contract_scan.py

isolation-scan: $(VENV)
	$(BIN)/python scripts/scan_isolation_integrity.py

# N8: GT never enters investigation path. Required before scored ScenarioRuns (N9).
test-isolation: $(VENV)
	$(BIN)/python scripts/scan_isolation_integrity.py
	$(PYTEST) tests/test_isolation_integrity_n8.py \
		tests/test_ground_truth_n2.py \
		tests/test_scenario_runner_n1.py::test_runner_cannot_select_ground_truth \
		tests/test_eval_entitlement.py \
		-q
	$(PYTEST) tests/test_sim_contract.py tests/test_sim_services.py -k "contract or forbidden" -q
	$(BIN)/python scripts/sim_contract_scan.py

sim-baseline-gate: $(VENV)
	./scripts/sim_baseline_gate.sh

sim-traffic: $(VENV)
	DURATION=$(DURATION) RPS=$(RPS) ./scripts/sim_traffic.sh

sim-inject: $(VENV)
	./scripts/sim_inject.sh $(ARGS)

scenario-list: $(VENV)
	PYTHONPATH="$(CURDIR)/scenario_runner:$(CURDIR)/simulation" \
		$(BIN)/python -m incidentpilot_scenario_runner list

scenario-run: $(VENV)
	PYTHONPATH="$(CURDIR)/scenario_runner:$(CURDIR)/simulation" \
		$(BIN)/python -m incidentpilot_scenario_runner run $(ARGS)

scenario-reset: $(VENV)
	PYTHONPATH="$(CURDIR)/scenario_runner:$(CURDIR)/simulation" \
		$(BIN)/python -m incidentpilot_scenario_runner reset

# N9: first scored vertical. Verify with: make scenario NAME=bad-deployment && make eval
# Do not inherit ambient shell NAME= (often the hostname); only honor CLI NAME=….
ifeq ($(origin NAME),command line)
  SCENARIO := $(NAME)
else
  SCENARIO ?= bad-deployment
endif
SCENARIO_PYTHONPATH := $(CURDIR)/scenario_runner:$(CURDIR)/simulation:$(CURDIR)/shared:$(CURDIR)/adapters:$(CURDIR)/evaluator

scenario: $(VENV)
	PYTHONPATH="$(SCENARIO_PYTHONPATH)" \
		$(BIN)/python -m incidentpilot_scenario_runner scored $(SCENARIO)

eval: $(VENV)
	PYTHONPATH="$(SCENARIO_PYTHONPATH)" \
		$(BIN)/python -m incidentpilot_scenario_runner eval --name $(SCENARIO)

obs-smoke:
	./scripts/verify_obs_stack.sh

openapi-export: $(VENV)
	$(BIN)/python scripts/export_openapi.py

api-run: $(VENV)
	cd api && PYTHONPATH="$(CURDIR)/api:$(CURDIR)/shared:$$PYTHONPATH" \
		../$(BIN)/python -m incidentpilot_api

web-dev:
	cd web && npm install && npm run dev

$(VENV):
	@echo "Missing $(VENV). Run: make bootstrap" >&2
	@exit 1
