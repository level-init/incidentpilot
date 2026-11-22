"""Q5: demo-app profile doc contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "demo-app.md"


def test_demo_app_doc_clarifies_optional_sample() -> None:
    assert DOC.is_file()
    text = DOC.read_text(encoding="utf-8")
    for needle in (
        "simulation/",
        "production IncidentPilot deploy",
        "compose-core",
        "PROFILE=simulation",
        "full",
        "evidence",
        "sim-inject",
        "connect-your-stack",
        "Your app",
    ):
        assert needle in text, needle


def test_readme_and_compose_call_out_demo_app() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/demo-app.md" in readme
    assert "Included demo app" in readme
    compose = (ROOT / "docs/local-compose.md").read_text(encoding="utf-8")
    assert "demo-app.md" in compose
    sim = (ROOT / "simulation/README.md").read_text(encoding="utf-8")
    assert "demo-app.md" in sim
