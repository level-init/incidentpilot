"""P8: demo-guide + demo_bad_deploy script contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "demo-guide.md"
SCRIPT = ROOT / "scripts" / "demo_bad_deploy.sh"


def test_demo_guide_covers_bad_deploy_and_pointers() -> None:
    assert DOC.is_file()
    text = DOC.read_text(encoding="utf-8")
    for needle in (
        "bad-deployment",
        "make demo-bad-deploy",
        "test-isolation",
        "make eval",
        "dependency-timeout",
        "cascading-failure",
        "quickstart.md",
        "Talking points",
    ):
        assert needle in text, needle


def test_demo_script_and_makefile() -> None:
    assert SCRIPT.is_file()
    script = SCRIPT.read_text(encoding="utf-8")
    assert "bad-deployment" in script
    assert "test-isolation" in script
    assert "make eval" in script
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "demo-bad-deploy" in makefile
    assert "demo_bad_deploy.sh" in makefile


def test_readme_links_demo_guide() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/demo-guide.md" in readme
    assert "demo-bad-deploy" in readme
