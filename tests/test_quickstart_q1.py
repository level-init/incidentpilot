"""Q1: Compose quickstart doc contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "quickstart.md"


def test_quickstart_doc_exists_with_golden_path() -> None:
    assert DOC.is_file()
    text = DOC.read_text(encoding="utf-8")
    for needle in (
        "make bootstrap",
        "make compose-core",
        "make migrate",
        "make api-run",
        "/webhooks/alerts/alertmanager",
        "dev-am-webhook-token",
        "Authorization: Bearer local-dev",
        "/incidents",
        "LLM_PROVIDER=gemini",
        "simulation",
        "Troubleshooting",
    ):
        assert needle in text, needle


def test_readme_links_quickstart() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/quickstart.md" in readme
    assert "Quickstart" in readme


def test_env_example_documents_gemini_byo() -> None:
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "LLM_PROVIDER=gemini" in env or "LLM_PROVIDER=fake" in env
    assert "LLM_API_KEY" in env or "GEMINI_API_KEY" in env
