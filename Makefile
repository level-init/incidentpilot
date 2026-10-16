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

.PHONY: bootstrap lint format typecheck test help

help:
	@echo "Targets:"
	@echo "  make bootstrap  - create .venv and install requirements-dev.txt"
	@echo "  make lint       - ruff check + format check + mypy"
	@echo "  make format     - ruff format (writes files)"
	@echo "  make typecheck  - mypy only"
	@echo "  make test       - pytest (scaffold smoke tests)"

bootstrap:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

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

$(VENV):
	@echo "Missing $(VENV). Run: make bootstrap" >&2
	@exit 1
