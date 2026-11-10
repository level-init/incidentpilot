"""D6: Temporal five-test regression suite — CI entry / manifest.

Bodies live in feature modules (I5 / J7 / J2 / D3 / K1) and are selected by
``pytest -m temporal_d6`` / ``make test-temporal-d6``. This module keeps the
suite contract visible and fails if a node is renamed away.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Canonical D6 nodes (must stay marked temporal_d6).
D6_NODES: tuple[tuple[str, str], ...] = (
    ("test_approval_wait_i5.py", "test_approval_wait_survives_worker_kill"),
    ("test_validation_window_j7.py", "test_validation_window_recovers"),
    ("test_remediation_rollback_j2.py", "test_retry_after_lost_ack_does_not_double_apply"),
    (
        "test_stale_revision_activity.py",
        "test_stale_revision_is_non_retryable_in_temporal",
    ),
    ("test_slack_notifier_k1.py", "test_slack_failure_leaves_mitigating_intact"),
)


def test_d6_suite_manifest_nodes_exist() -> None:
    """Harness contract: five named regressions remain discoverable."""
    assert len(D6_NODES) == 5
    missing: list[str] = []
    for filename, test_name in D6_NODES:
        path = ROOT / filename
        if not path.is_file():
            missing.append(f"{filename} (file)")
            continue
        text = path.read_text(encoding="utf-8")
        if f"def {test_name}" not in text:
            missing.append(f"{filename}::{test_name}")
        elif "@pytest.mark.temporal_d6" not in text:
            # Marker must appear in the module (on the D6 test).
            missing.append(f"{filename} missing temporal_d6 marker")
    assert missing == [], f"D6 suite drift: {missing}"
