"""D1: Temporal task queue constants, Freeze-9 mapping, subscribe smoke."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from incidentpilot_shared.temporal_queues import (
    ALL_TASK_QUEUES,
    QUEUE_CONSUMER_CONTRACTS,
    TaskQueue,
    contract_for,
    queues_for_process,
)
from incidentpilot_shared.temporal_runtime import run_smoke_subscribe

ROOT = Path(__file__).resolve().parents[1]


def _temporal_reachable() -> bool:
    host_port = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    host, _, port_s = host_port.partition(":")
    port = int(port_s or "7233")
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def test_three_queues_defined() -> None:
    assert ALL_TASK_QUEUES == (
        TaskQueue.GENERAL,
        TaskQueue.EVIDENCE,
        TaskQueue.REMEDIATION,
    )
    assert TaskQueue.GENERAL == "incidentpilot-general"
    assert TaskQueue.EVIDENCE == "incidentpilot-evidence"
    assert TaskQueue.REMEDIATION == "incidentpilot-remediation"


def test_freeze9_consumer_mapping() -> None:
    assert len(QUEUE_CONSUMER_CONTRACTS) == 3
    assert contract_for(TaskQueue.GENERAL).consumer_process == "incidentpilot-worker"
    assert contract_for(TaskQueue.EVIDENCE).consumer_process == "evidence-worker"
    assert contract_for(TaskQueue.REMEDIATION).consumer_process == "remediation-worker"
    assert queues_for_process("incidentpilot-worker") == (TaskQueue.GENERAL,)
    assert queues_for_process("evidence-worker") == (TaskQueue.EVIDENCE,)
    assert queues_for_process("remediation-worker") == (TaskQueue.REMEDIATION,)


def test_queue_docs_exist() -> None:
    doc = (ROOT / "docs" / "temporal-queues.md").read_text(encoding="utf-8")
    for name in ALL_TASK_QUEUES:
        assert name in doc
    assert "incidentpilot-worker" in doc
    assert "evidence-worker" in doc
    assert "remediation-worker" in doc


@pytest.mark.skipif(not _temporal_reachable(), reason="Temporal not reachable")
def test_workers_subscribe_without_errors() -> None:
    names = run_smoke_subscribe(ALL_TASK_QUEUES, hold_seconds=0.75)
    assert set(names) == {str(q) for q in ALL_TASK_QUEUES}
