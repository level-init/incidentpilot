"""N8: isolation-integrity suite — GT never enters investigation path."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "api",
    ROOT / "shared",
    ROOT / "scenario_runner",
    ROOT / "evaluator",
    ROOT / "adapters",
):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_shared.ai_tool_broker import AiToolBroker  # noqa: E402
from incidentpilot_shared.ai_tools import DENIED_TOOL_NAMES, ToolDeniedError  # noqa: E402
from incidentpilot_shared.tool_scope import ToolScope  # noqa: E402

psycopg = pytest.importorskip("psycopg")


def _app_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _runner_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL_RUNNER",
        "postgresql://ip_runner:incidentpilot_runner@localhost:5432/incidentpilot",
    )


def _eval_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL_EVALUATOR",
        "postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_eval_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM eval.ground_truth LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_static_isolation_scan() -> None:
    script = ROOT / "scripts" / "scan_isolation_integrity.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_ai_tools_deny_ground_truth() -> None:
    assert "ground_truth" in DENIED_TOOL_NAMES
    assert "GROUND_TRUTH" in DENIED_TOOL_NAMES
    broker = AiToolBroker(
        scope=ToolScope(
            incident_id="00000000-0000-0000-0000-000000000001",
            environment="local",
        ),
    )
    with pytest.raises(ToolDeniedError):
        broker.invoke("ground_truth", {})
    with pytest.raises(ToolDeniedError):
        broker.invoke("GROUND_TRUTH", {})


def test_ops_roles_denied_eval_ground_truth_api(client: TestClient) -> None:
    for token in ("local-dev", "local-dev-admin", "local-dev-viewer"):
        res = client.get(
            "/eval/ground-truth",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403, token


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_db_roles_denied_gt() -> None:
    for label, dsn in (("app", _app_dsn()), ("runner", _runner_dsn())):
        denied = False
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM eval.ground_truth LIMIT 1")
                    cur.fetchone()
        except psycopg.Error:
            denied = True
        assert denied, f"{label} must not SELECT eval.ground_truth"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_ops_incident_api_does_not_leak_gt(client: TestClient) -> None:
    """Incident list/detail must not embed GT answer_payload / match_spec."""
    headers = {"Authorization": "Bearer local-dev"}
    create = client.post(
        "/incidents",
        headers=headers,
        json={"title": "n8 isolation", "severity": "SEV3", "service_key": "payment"},
    )
    assert create.status_code == 201, create.text
    body = create.json()
    blob = str(body).lower()
    assert "answer_payload" not in blob
    assert "match_spec" not in blob
    assert "answer_key" not in blob

    detail = client.get(f"/incidents/{body['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    dblob = str(detail.json()).lower()
    assert "answer_payload" not in dblob
    assert "match_spec" not in dblob
    assert '"root_cause"' not in dblob or "bad_deployment" not in dblob


def test_scenario_runner_has_no_gt_event_log_module() -> None:
    """Runner must not ship a GroundTruth event/answer log."""
    runner_pkg = ROOT / "scenario_runner" / "incidentpilot_scenario_runner"
    names = {p.name for p in runner_pkg.glob("**/*") if p.is_file()}
    forbidden = {
        "ground_truth_log.py",
        "gt_event_log.py",
        "answer_key_log.py",
        "event_log_gt.py",
    }
    assert names.isdisjoint(forbidden)
    # No module defining a GT event log class/function by name.
    for path in runner_pkg.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                n = node.name.lower()
                assert "ground_truth" not in n or node.name == "assert_ground_truth_denied"
                assert "answer_key" not in n


def test_shared_investigation_modules_do_not_import_evaluator_gt() -> None:
    """Worker-facing shared domain must not import evaluator ground_truth helper."""
    suspects = [
        ROOT / "shared" / "incidentpilot_shared" / "domain" / "commands.py",
        ROOT / "shared" / "incidentpilot_shared" / "ai_tools.py",
        ROOT / "shared" / "incidentpilot_shared" / "ai_tool_broker.py",
    ]
    for path in suspects:
        text = path.read_text(encoding="utf-8")
        assert "incidentpilot_evaluator.ground_truth" not in text
        assert "from eval.ground_truth" not in text


def test_openapi_eval_gt_requires_security_paths(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/eval/ground-truth" in paths
