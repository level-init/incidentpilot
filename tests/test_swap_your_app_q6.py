"""Q6: swap-your-app guide contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "swap-your-app.md"


def test_swap_guide_is_profile_not_delete() -> None:
    assert DOC.is_file()
    text = DOC.read_text(encoding="utf-8")
    for needle in (
        "simulation",
        "not delete",
        "compose-core",
        "connect-your-stack",
        "/webhooks/alerts/alertmanager",
        "Minimum signals",
        "evidence",
    ):
        assert needle in text, needle


def test_cross_links() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/swap-your-app.md" in readme
    demo = (ROOT / "docs/demo-app.md").read_text(encoding="utf-8")
    assert "swap-your-app.md" in demo
    connect = (ROOT / "docs/connect-your-stack.md").read_text(encoding="utf-8")
    assert "swap-your-app.md" in connect
    qs = (ROOT / "docs/quickstart.md").read_text(encoding="utf-8")
    assert "swap-your-app.md" in qs
