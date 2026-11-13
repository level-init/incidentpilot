"""N17: Eval UI source contracts — separate from ops; FAILED ≠ scored miss."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


def _read(*parts: str) -> str:
    return (WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_ops_incident_surfaces_have_no_ground_truth_navigation() -> None:
    """AC: no GT navigation from ops Incident Detail (or ops list)."""
    ops_paths = [
        WEB / "app" / "incidents",
        WEB / "components" / "ManualResolvePanel.tsx",
        WEB / "components" / "PostmortemPanel.tsx",
        WEB / "components" / "RemediationPanel.tsx",
        WEB / "components" / "EvidenceHypothesesPanes.tsx",
        WEB / "components" / "InvestigationContext.tsx",
        WEB / "components" / "AuditTrailPanel.tsx",
        WEB / "components" / "AiProvenancePanel.tsx",
        WEB / "components" / "ServiceDependencyMap.tsx",
    ]
    forbidden = (
        "/eval/ground-truth",
        "ground-truth",
        "ground_truth",
        "GroundTruth",
        "listGroundTruth",
    )
    for path in ops_paths:
        texts: list[str] = []
        if path.is_file():
            texts.append(path.read_text(encoding="utf-8"))
        else:
            for f in path.rglob("*.tsx"):
                texts.append(f.read_text(encoding="utf-8"))
        blob = "\n".join(texts)
        for needle in forbidden:
            assert needle not in blob, f"{path} must not mention {needle!r}"


def test_eval_routes_and_labels_exist() -> None:
    runs_page = _read("app", "eval", "page.tsx")
    detail = _read("app", "eval", "runs", "[id]", "page.tsx")
    gt = _read("app", "eval", "ground-truth", "page.tsx")
    labels = _read("lib", "eval.ts")
    shell = _read("components", "AppShell.tsx")
    banner = _read("components", "EvalSnapshotBanner.tsx")

    assert 'requireEval' in runs_page
    assert 'requireEval' in detail
    assert 'requireEval' in gt
    assert "classifyScenarioRun" in runs_page
    assert "INVALID RUN" in labels
    assert "SCORED MISS" in labels
    assert "passed=false" in labels
    assert "not a scored miss" in labels
    assert "Immutable snapshot" in banner
    assert 'href: "/eval"' in shell
    assert 'href: "/eval/ground-truth"' in shell
    assert "requireEval" in shell


def test_login_exposes_evaluator_persona() -> None:
    auth = _read("lib", "auth.ts")
    login = _read("app", "login", "page.tsx")
    assert "local-dev-evaluator" in auth
    assert "Evaluator" in auth
    assert "local-dev-evaluator" in login
