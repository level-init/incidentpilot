"""G7: COLLECTOR_TRIGGER from general worker — no Prom/Loki/Tempo secrets."""

from __future__ import annotations

import ast
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("temporalio")
pytest.importorskip("pytest_asyncio")

from temporalio import activity, workflow  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from incidentpilot_adapters.telemetry.loki import LokiQueryResult  # noqa: E402
from incidentpilot_adapters.telemetry.prometheus import PrometheusQueryResult  # noqa: E402
from incidentpilot_adapters.telemetry.tempo import TempoQueryResult  # noqa: E402
from incidentpilot_shared.temporal_queues import (  # noqa: E402
    GENERAL_FORBIDDEN_ENV,
    TaskQueue,
    contract_for,
)
from incidentpilot_worker.activities.collect_cycle import (  # noqa: E402
    run_collect_cycle,
    validate_collect_job_scope,
)
from incidentpilot_worker.activities.collector_trigger import (  # noqa: E402
    TriggerCollectCycleInput,
    trigger_collect_cycle,
)
from incidentpilot_worker.activities.incident_transitions import (  # noqa: E402
    advance_incident_state,
    load_incident_snapshot,
)
from incidentpilot_worker.workflows.collect_cycle import CollectCycleWorkflow  # noqa: E402
from incidentpilot_worker.workflows.incident_workflow import (  # noqa: E402
    IncidentWorkflow,
    IncidentWorkflowInput,
)

ROOT = Path(__file__).resolve().parents[1]
_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="g7-test-act")

# Modules reachable when running the general worker (must not mention telemetry creds).
_GENERAL_AUDIT_PATHS = [
    ROOT / "worker" / "incidentpilot_worker" / "worker_factory.py",
    ROOT / "worker" / "incidentpilot_worker" / "__main__.py",
    ROOT / "worker" / "incidentpilot_worker" / "activities" / "collector_trigger.py",
    ROOT / "worker" / "incidentpilot_worker" / "activities" / "incident_transitions.py",
    ROOT / "worker" / "incidentpilot_worker" / "activities" / "__init__.py",
    ROOT / "worker" / "incidentpilot_worker" / "workflows" / "__init__.py",
    ROOT / "worker" / "incidentpilot_worker" / "workflows" / "incident_workflow.py",
]

_FORBIDDEN_NAMES = frozenset(
    {
        "PROMETHEUS_URL",
        "LOKI_URL",
        "TEMPO_URL",
        "PrometheusClient",
        "LokiClient",
        "TempoClient",
        "collect_prometheus_metrics",
        "collect_loki_logs",
        "collect_tempo_traces",
        "run_collect_cycle",
        "validate_collect_job_scope",
        "CollectCycleWorkflow",
    }
)


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.evidence LIMIT 1")
            return True
    except Exception:
        return False


def _ast_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
        elif isinstance(node, ast.alias):
            if node.name:
                names.add(node.name.split(".")[-1])
            if node.asname:
                names.add(node.asname)
    return names


def test_general_forbidden_env_constant() -> None:
    assert GENERAL_FORBIDDEN_ENV == frozenset({"PROMETHEUS_URL", "LOKI_URL", "TEMPO_URL"})
    assert contract_for(TaskQueue.GENERAL).privilege_class == "orchestration"
    assert contract_for(TaskQueue.EVIDENCE).privilege_class == "collector"


def test_general_worker_modules_have_no_telemetry_creds() -> None:
    """Config audit: general-reachable code must not name Prom/Loki/Tempo secrets/clients."""
    offenders: list[str] = []
    for path in _GENERAL_AUDIT_PATHS:
        found = _ast_names(path) & _FORBIDDEN_NAMES
        # worker_factory may mention CollectCycleWorkflow only as a *string* inside
        # the evidence branch after a local import — ban top-level identifiers via AST
        # of the whole file is too blunt for lazy import names used as import targets.
        # Allow lazy import symbols only inside worker_factory.py evidence branch by
        # checking they never appear outside ImportFrom inside nested functions...
        # Simpler rule: ban env + client names everywhere; ban collector activity
        # names except as ImportFrom inside functions in worker_factory.py.
        if path.name == "worker_factory.py":
            found -= {
                "CollectCycleWorkflow",
                "collect_prometheus_metrics",
                "collect_loki_logs",
                "collect_tempo_traces",
                "run_collect_cycle",
                "validate_collect_job_scope",
            }
            text = path.read_text(encoding="utf-8")
            # Top-level (module) imports must not pull collectors.
            tree = ast.parse(text)
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported = {a.name for a in node.names}
                    bad = imported & {
                        "CollectCycleWorkflow",
                        "collect_prometheus_metrics",
                        "collect_loki_logs",
                        "collect_tempo_traces",
                        "run_collect_cycle",
                        "validate_collect_job_scope",
                        "PrometheusClient",
                        "LokiClient",
                        "TempoClient",
                    }
                    if bad:
                        offenders.append(f"{path.relative_to(ROOT)}:top-import:{sorted(bad)}")
            env_hits = _ast_names(path) & GENERAL_FORBIDDEN_ENV
            if env_hits:
                offenders.append(f"{path.relative_to(ROOT)}:{sorted(env_hits)}")
            continue
        if found:
            offenders.append(f"{path.relative_to(ROOT)}:{sorted(found)}")
    assert offenders == []


def test_general_worker_registers_trigger_not_collectors() -> None:
    from incidentpilot_worker.worker_factory import build_worker

    # Inspect source registration list without needing a live Temporal client.
    src = (ROOT / "worker" / "incidentpilot_worker" / "worker_factory.py").read_text(
        encoding="utf-8"
    )
    general_block = src.split("if queue is TaskQueue.GENERAL:")[1].split(
        "if queue is TaskQueue.EVIDENCE:"
    )[0]
    assert "trigger_collect_cycle" in general_block
    assert "kickoff_collect_cycle" in general_block
    assert "collect_prometheus_metrics" not in general_block
    assert "run_collect_cycle" not in general_block
    assert "CollectCycleWorkflow" not in general_block
    _ = build_worker


@dataclass
class _FakeProm:
    def query_range(
        self,
        query: str,
        *,
        start: float,
        end: float,
        step: str = "30s",
        max_series: int = 20,
    ) -> PrometheusQueryResult:
        return PrometheusQueryResult(
            query=query,
            start=start,
            end=end,
            step=step,
            result_type="matrix",
            series=[{"metric": {"__name__": "up"}, "values": [[start, "1"]]}],
        )


@dataclass
class _FakeLoki:
    def query_range(
        self,
        query: str,
        *,
        start: float,
        end: float,
        limit: int = 100,
        max_streams: int = 10,
    ) -> LokiQueryResult:
        return LokiQueryResult(
            query=query,
            start_ns=int(start * 1e9),
            end_ns=int(end * 1e9),
            streams=[{"stream": {"job": "sim"}, "values": [["1", "error"]]}],
        )


@dataclass
class _FakeTempo:
    def search(
        self,
        query: str,
        *,
        start: float,
        end: float,
        limit: int = 20,
    ) -> TempoQueryResult:
        return TempoQueryResult(
            query=query,
            start=start,
            end=end,
            traces=[{"traceID": "abc", "rootServiceName": "checkout", "durationMs": 12}],
        )


@pytest.fixture()
def incident_id() -> Iterator[uuid.UUID]:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G7 trigger', 1)
            """,
            (str(iid), f"INC-G7-{iid.hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO domain.service (key, display_name, environment)
            VALUES (%s, %s, 'local')
            ON CONFLICT (key, environment) DO UPDATE SET display_name = EXCLUDED.display_name
            RETURNING id
            """,
            (f"svc-g7-{iid.hex[:6]}", f"svc-g7-{iid.hex[:6]}"),
        )
        service_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO domain.incident_service (incident_id, service_id, involvement)
            VALUES (%s, %s, 'affected')
            ON CONFLICT DO NOTHING
            """,
            (str(iid), str(service_id)),
        )
        conn.commit()
    yield iid


@workflow.defn(name="TriggerCollectHarness")
class TriggerCollectHarness:
    """Tiny workflow so general activity can use activity.client() in tests."""

    @workflow.run
    async def run(self, payload: TriggerCollectCycleInput) -> dict[str, object]:
        return await workflow.execute_activity(
            trigger_collect_cycle,
            payload,
            start_to_close_timeout=__import__("datetime").timedelta(seconds=60),
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
@pytest.mark.asyncio
async def test_trigger_collect_cycle_from_general_starts_evidence_job(
    incident_id: uuid.UUID,
) -> None:
    general_q = f"test-g7-gen-{uuid.uuid4().hex[:8]}"
    evidence_q = f"test-g7-ev-{uuid.uuid4().hex[:8]}"
    cycle_id = uuid.uuid4().hex
    start, end = 1_700_400_000.0, 1_700_400_600.0

    os.environ["COLLECT_CYCLE_TASK_QUEUE"] = evidence_q
    try:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with (
                Worker(
                    env.client,
                    task_queue=general_q,
                    workflows=[IncidentWorkflow, TriggerCollectHarness],
                    activities=[
                        load_incident_snapshot,
                        advance_incident_state,
                        trigger_collect_cycle,
                    ],
                    activity_executor=_ACTIVITY_EXECUTOR,
                ),
                Worker(
                    env.client,
                    task_queue=evidence_q,
                    workflows=[CollectCycleWorkflow],
                    activities=[validate_collect_job_scope, run_collect_cycle],
                    activity_executor=_ACTIVITY_EXECUTOR,
                ),
            ):
                from incidentpilot_shared.incident_workflow import incident_workflow_id

                incident_handle = await env.client.start_workflow(
                    IncidentWorkflow.run,
                    IncidentWorkflowInput(
                        incident_id=str(incident_id),
                        wait_for_evidence_updated=True,
                    ),
                    id=incident_workflow_id(incident_id),
                    task_queue=general_q,
                )

                with (
                    patch(
                        "incidentpilot_worker.collectors.PrometheusClient",
                        return_value=_FakeProm(),
                    ),
                    patch(
                        "incidentpilot_worker.collectors.LokiClient",
                        return_value=_FakeLoki(),
                    ),
                    patch(
                        "incidentpilot_worker.collectors.TempoClient",
                        return_value=_FakeTempo(),
                    ),
                ):
                    trigger_handle = await env.client.start_workflow(
                        TriggerCollectHarness.run,
                        TriggerCollectCycleInput(
                            incident_id=str(incident_id),
                            environment="local",
                            collector="metrics",
                            query="up",
                            cycle_id=cycle_id,
                            window_start=start,
                            window_end=end,
                        ),
                        id=f"trigger-{cycle_id}",
                        task_queue=general_q,
                    )
                    trigger_result = await trigger_handle.result()

                assert trigger_result["started"] is True
                assert trigger_result["cycle_id"] == cycle_id
                assert await incident_handle.query(IncidentWorkflow.evidence_updated_count) == 1
                assert await incident_handle.result() == "INVESTIGATING"
    finally:
        os.environ.pop("COLLECT_CYCLE_TASK_QUEUE", None)

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM domain.evidence WHERE incident_id = %s AND kind = 'METRIC'",
            (str(incident_id),),
        )
        assert int(cur.fetchone()[0]) >= 1


def test_trigger_collect_cycle_is_async_activity() -> None:
    """Uses activity.client() — must be async, not a sync Prom scrape."""
    import inspect

    assert inspect.iscoroutinefunction(trigger_collect_cycle)
    _ = activity  # imported for Temporal activity module presence
