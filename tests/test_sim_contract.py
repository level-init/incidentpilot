"""E6: sim contract forbids GT / root-cause APIs and answer-key fields."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "simulation"
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))

from common.contract import (  # noqa: E402
    FORBIDDEN_FIELD_MARKERS,
    FORBIDDEN_PATH_MARKERS,
    field_is_forbidden,
    path_is_forbidden,
    scan_all,
    scan_apps,
    scan_openapi,
    scan_simulation_sources,
)

SERVICES = ("auth", "checkout", "payment", "inventory", "notification", "gateway")


def _app(name: str):
    return importlib.import_module(f"{name}.app").app


def test_live_services_pass_full_contract() -> None:
    apps = [(n, _app(n)) for n in SERVICES]
    assert scan_all(sim_root=SIM, apps=apps) == []


def test_path_and_field_markers() -> None:
    assert path_is_forbidden("/v1/actual-root-cause")
    assert path_is_forbidden("/internal/ground_truth")
    assert field_is_forbidden("ground_truth")
    assert field_is_forbidden("answer_key")
    assert not field_is_forbidden("user_id")
    assert "ground_truth" in FORBIDDEN_FIELD_MARKERS
    assert "actual-root-cause" in FORBIDDEN_PATH_MARKERS


def test_forbidden_route_fails_scan() -> None:
    app = FastAPI()

    @app.get("/v1/ground_truth")
    def cheat() -> dict[str, str]:
        return {"nope": "yes"}

    violations = scan_apps([("probe", app)])
    assert any("ground_truth" in v for v in violations)


def test_forbidden_openapi_field_fails_scan() -> None:
    class CheatOut(BaseModel):
        ground_truth: str = Field(description="must never ship")

    app = FastAPI()

    @app.get("/v1/orders/{order_id}", response_model=CheatOut)
    def get_order(order_id: str) -> CheatOut:
        return CheatOut(ground_truth="payment")

    violations = scan_openapi(app, service="probe")
    assert any("ground_truth" in v for v in violations)


def test_forbidden_source_ast_fails_scan(tmp_path: Path) -> None:
    bad = tmp_path / "evil.py"
    bad.write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        '@app.get("/v1/actual-root-cause")\n'
        "def oracle():\n"
        "    return {}\n",
        encoding="utf-8",
    )
    violations = scan_simulation_sources(tmp_path)
    assert any("actual-root-cause" in v for v in violations)


def test_scan_all_includes_source_and_apps(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("X = 1\n", encoding="utf-8")
    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    assert scan_all(sim_root=tmp_path, apps=[("ok", app)]) == []
