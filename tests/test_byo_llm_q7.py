"""Q7: BYO Gemini / LLM self-host doc contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "byo-llm.md"


def test_byo_llm_doc_defaults_fake_and_byo_gemini() -> None:
    assert DOC.is_file()
    text = DOC.read_text(encoding="utf-8")
    for needle in (
        "LLM_PROVIDER=fake",
        "LLM_PROVIDER=gemini",
        "LLM_API_KEY",
        "GEMINI_API_KEY",
        "general",
        "never commit",
        "evidence-worker",
        "your-key-here",
        "Bring your own",
    ):
        assert needle in text, needle


def test_discoverability() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/byo-llm.md" in readme
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "docs/byo-llm.md" in env
    assert "LLM_PROVIDER=fake" in env
    qs = (ROOT / "docs/quickstart.md").read_text(encoding="utf-8")
    assert "byo-llm.md" in qs
    llm = (ROOT / "docs/llm.md").read_text(encoding="utf-8")
    assert "byo-llm.md" in llm
