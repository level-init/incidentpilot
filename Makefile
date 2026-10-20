# IncidentPilot local quality gates (A3 / #2).
# Prefer: make bootstrap && make lint && make test

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip
RUFF := $(BIN)/ruff
MYPY := $(BIN)/mypy
PYTEST := $(BIN)/pytest

PY_SRC := api worker remediation_worker shared adapters scenario_runner evaluator

COMPOSE ?= docker compose
PROFILE ?= core

.PHONY: bootstrap lint format typecheck test help \
	compose-core compose-full compose-up compose-down compose-ps compose-config \
	migrate db-verify-isolation verify-local-infra openapi-export api-run

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
	@echo "  make openapi-export        - write openapi/openapi.json"
	@echo "  make api-run               - run FastAPI on :8000"

bootstrap:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt

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

openapi-export: $(VENV)
	$(BIN)/python scripts/export_openapi.py

api-run: $(VENV)
	cd api && PYTHONPATH="$(CURDIR)/api:$(CURDIR)/shared:$$PYTHONPATH" \
		../$(BIN)/python -m incidentpilot_api

$(VENV):
	@echo "Missing $(VENV). Run: make bootstrap" >&2
	@exit 1
