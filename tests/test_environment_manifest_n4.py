"""N4: environment_manifest capture + pin on ScenarioRun."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "api",
    ROOT / "shared",
    ROOT / "scenario_runner",
    ROOT / "evaluator",
):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_scenario_runner.baseline import BaselineGateResult  # noqa: E402
from incidentpilot_scenario_runner.db import get_scenario_run  # noqa: E402
from incidentpilot_scenario_runner.runner import run_scenario  # noqa: E402
from incidentpilot_shared.environment_manifest import (  # noqa: E402
    capture_local_manifest,
    get_environment_manifest,
)
from incidentpilot_shared.scenario_lifecycle import mark_evaluated  # noqa: E402

psycopg = pytest.importorskip("psycopg")


def _eval_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL_EVALUATOR",
        "postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_eval_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'scenarios'
                      AND table_name = 'environment_manifest'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_capture_local_manifest_shape() -> None:
    m = capture_local_manifest(environment_class="local")
    assert m["environment_class"] == "local"
    assert m["python_version"]
    assert m["platform"]
    assert isinstance(m["image_digests"], dict)


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0022 not reachable")
def test_local_scored_run_pins_manifest(client: TestClient) -> None:
    outcome = run_scenario(
        "bad_deploy",
        baseline_fn=lambda: BaselineGateResult(
            ok=True, payload={"ok": True}, detail="ok"
        ),
        inject=False,
    )
    # Advance to FAULT_INJECTED without real inject for evaluate path
    from incidentpilot_scenario_runner.db import get_runner_conn, mark_fault_injected

    # run_scenario with inject=False stops at BASELINE_PASSED — force inject mark
    # by creating a FAULT_INJECTED sibling via evaluate prerequisites:
    with get_runner_conn() as conn:
        row = get_scenario_run(conn, outcome.run_id)
        assert row["environment_manifest_id"] is not None
        mid = row["environment_manifest_id"]
        manifest = get_environment_manifest(conn, manifest_id=mid)
        assert manifest.environment_class == "local"
        assert manifest.python_version

        # Move BASELINE_PASSED → FAULT_INJECTED for scored pin check
        if row["status"] == "BASELINE_PASSED":
            mark_fault_injected(conn, run_id=outcome.run_id)

    with psycopg.connect(_eval_dsn()) as conn:
        scored = mark_evaluated(
            conn,
            run_id=outcome.run_id,
            passed=True,
            summary={"n4": "pin-check"},
            commit=True,
        )
        assert scored.status == "EVALUATED"
        assert scored.environment_manifest_id is not None
        assert scored.environment_manifest is not None
        assert scored.environment_manifest["environment_class"] == "local"
        assert scored.environment_manifest.get("python_version")

    res = client.get(
        f"/eval/scenario-runs/{outcome.run_id}",
        headers={"Authorization": "Bearer local-dev-evaluator"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "EVALUATED"
    assert body["environment_manifest_id"]
    assert body["environment_manifest"]["environment_class"] == "local"
    assert body["environment_manifest"]["python_version"]


def test_openapi_includes_manifest(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "EnvironmentManifestOut" in schemas
    props = schemas["ScenarioRunOut"]["properties"]
    assert "environment_manifest" in props
    assert "environment_manifest_id" in props
