"""O2: Helm chart layout + values schema contracts (helm binary optional)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "incidentpilot"
ENVS = ("local", "staging", "production-demo")
COMPONENTS = (
    "api",
    "worker",
    "evidenceWorker",
    "remediation",
    "web",
    "evaluator",
    "scenarioRunner",
)


def test_chart_metadata_and_templates() -> None:
    assert (CHART / "Chart.yaml").is_file()
    assert (CHART / "values.yaml").is_file()
    assert (CHART / "values.schema.json").is_file()
    for name in (
        "api.yaml",
        "worker.yaml",
        "evidence-worker.yaml",
        "remediation.yaml",
        "web.yaml",
        "evaluator.yaml",
        "scenario-runner.yaml",
        "configmap.yaml",
        "namespace.yaml",
        "_helpers.tpl",
        "NOTES.txt",
    ):
        assert (CHART / "templates" / name).is_file(), name


def test_per_env_values_files() -> None:
    for env in ENVS:
        path = CHART / f"values-{env}.yaml"
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert f"environment: {env}" in text or f'environment: "{env}"' in text


def test_values_schema_enforces_environments() -> None:
    schema = json.loads((CHART / "values.schema.json").read_text(encoding="utf-8"))
    env_enum = schema["properties"]["global"]["properties"]["environment"]["enum"]
    assert set(env_enum) == set(ENVS)
    sa = schema["properties"]["serviceAccounts"]["required"]
    for key in ("api", "worker", "evidence", "remediation", "evaluator", "runner", "web"):
        assert key in sa


def test_defaults_cover_components_and_no_admin_sa() -> None:
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    for c in COMPONENTS:
        assert f"{c}:" in values
    assert "incidentpilot-admin" not in values
    assert "cluster-admin" not in values.lower()


def test_validate_script_exists() -> None:
    script = ROOT / "scripts" / "helm_validate.sh"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "helm lint" in text
    assert "helm template" in text
    for env in ENVS:
        assert env in text
