"""O7: kind/k3d Helm chart CI smoke contracts."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
SCRIPT = ROOT / "scripts" / "helm_kind_smoke.sh"


def test_smoke_script_exists_and_is_safe() -> None:
    assert SCRIPT.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "helm upgrade --install" in text
    assert "--wait=false" in text
    assert "incidentpilot-api" in text
    assert "privilege-class" in text
    # Must not require AWS / Temporal Cloud for PR CI.
    assert "TEMPORAL_API_KEY" not in text
    assert "enable_expensive_resources" not in text


def test_ci_has_helm_kind_job() -> None:
    data = yaml.safe_load(CI.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or {}
    assert "helm-kind" in jobs
    job = jobs["helm-kind"]
    steps = job.get("steps") or []
    joined = "\n".join(
        f"{s.get('uses', '')}\n{s.get('run', '')}\n{s.get('name', '')}" for s in steps
    )
    assert "kind-action" in joined or "kind create" in joined
    assert "helm_kind_smoke" in joined or "helm-kind-smoke" in joined
    assert "helm-validate" in joined or "helm_validate" in joined


def test_docs_and_makefile() -> None:
    assert (ROOT / "docs/helm-kind.md").is_file()
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "helm-kind-smoke" in makefile
