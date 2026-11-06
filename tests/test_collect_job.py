"""G6: CollectJob on evidence queue → EvidenceUpdated signal; scope server-side."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from unittest.mock import patch

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("temporalio")
pytest.importorskip("pytest_asyncio")

from temporalio.client import WorkflowFailureError  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from incidentpilot_adapters.telemetry.loki import LokiQueryResult  # noqa: E402
from incidentpilot_adapters.telemetry.prometheus import PrometheusQueryResult  # noqa: E402
from incidentpilot_adapters.telemetry.tempo import TempoQueryResult  # noqa: E402
from incidentpilot_shared.collect_job import (  # noqa: E402
    CollectJob,
    collect_cycle_workflow_id,
)
from incidentpilot_shared.incident_workflow import incident_workflow_id  # noqa: E402
from incidentpilot_shared.temporal_queues import TaskQueue, contract_for  # noqa: E402
from incidentpilot_worker.activities.collect_cycle import (  # noqa: E402
    run_collect_cycle,
    validate_collect_job_scope,
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

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="g6-test-act")


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


@pytest.fixture()
def incident_id() -> Iterator[uuid.UUID]:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G6 collect', 1)
            """,
            (str(iid), f"INC-G6-{iid.hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO domain.service (key, display_name, environment)
            VALUES (%s, %s, 'local')
            ON CONFLICT (key, environment) DO UPDATE SET display_name = EXCLUDED.display_name
            RETURNING id
            """,
            (f"svc-{iid.hex[:6]}", f"svc-{iid.hex[:6]}"),
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


def _patch_telemetry():
    return (
        patch("incidentpilot_worker.collectors.PrometheusClient", return_value=_FakeProm()),
        patch("incidentpilot_worker.collectors.LokiClient", return_value=_FakeLoki()),
        patch("incidentpilot_worker.collectors.TempoClient", return_value=_FakeTempo()),
    )


def test_collect_job_schema_rejects_unknown_collector() -> None:
    with pytest.raises(ValueError, match="unsupported collectors"):
        CollectJob(
            incident_id=str(uuid.uuid4()),
            environment="local",
            collectors=("metrics", "changes"),
        )


def test_evidence_queue_owns_collect_cycle() -> None:
    assert contract_for(TaskQueue.EVIDENCE).privilege_class == "collector"
    assert contract_for(TaskQueue.GENERAL).privilege_class != "collector"
    # Evidence symbols are lazy-imported inside build_worker (G7); load them here.
    from incidentpilot_worker.activities.collect_cycle import (
        run_collect_cycle,
        validate_collect_job_scope,
    )

    assert CollectCycleWorkflow is not None
    assert callable(validate_collect_job_scope)
    assert callable(run_collect_cycle)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
@pytest.mark.asyncio
async def test_collect_cycle_signals_incident_workflow(incident_id: uuid.UUID) -> None:
    general_q = f"test-g6-gen-{uuid.uuid4().hex[:8]}"
    evidence_q = f"test-g6-ev-{uuid.uuid4().hex[:8]}"
    cycle_id = uuid.uuid4().hex
    start, end = 1_700_300_000.0, 1_700_300_900.0

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with (
            Worker(
                env.client,
                task_queue=general_q,
                workflows=[IncidentWorkflow],
                activities=[load_incident_snapshot, advance_incident_state],
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
            incident_handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_for_evidence_updated=True,
                ),
                id=incident_workflow_id(incident_id),
                task_queue=general_q,
            )

            patches = _patch_telemetry()
            with patches[0], patches[1], patches[2]:
                collect_handle = await env.client.start_workflow(
                    CollectCycleWorkflow.run,
                    CollectJob(
                        incident_id=str(incident_id),
                        environment="local",
                        cycle_id=cycle_id,
                        window_start=start,
                        window_end=end,
                    ),
                    id=collect_cycle_workflow_id(incident_id, cycle_id),
                    task_queue=evidence_q,
                )
                collect_result = await collect_handle.result()

            assert collect_result["inserted_count"] >= 1
            assert await incident_handle.query(IncidentWorkflow.evidence_updated_count) == 1
            last = await incident_handle.query(IncidentWorkflow.last_evidence_updated)
            assert last is not None
            assert last.cycle_id == cycle_id
            assert await incident_handle.result() == "INVESTIGATING"

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM domain.evidence WHERE incident_id = %s",
            (str(incident_id),),
        )
        assert int(cur.fetchone()[0]) >= 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
@pytest.mark.asyncio
async def test_collect_job_rejects_cross_env_scope(incident_id: uuid.UUID) -> None:
    """Queue alone is not authz — wrong environment fails before collect/signal."""
    evidence_q = f"test-g6-ev-{uuid.uuid4().hex[:8]}"
    cycle_id = uuid.uuid4().hex

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=evidence_q,
            workflows=[CollectCycleWorkflow],
            activities=[validate_collect_job_scope, run_collect_cycle],
            activity_executor=_ACTIVITY_EXECUTOR,
        ):
            collect_handle = await env.client.start_workflow(
                CollectCycleWorkflow.run,
                CollectJob(
                    incident_id=str(incident_id),
                    environment="production-demo",
                    cycle_id=cycle_id,
                    window_start=1.0,
                    window_end=2.0,
                    collectors=("metrics",),
                ),
                id=collect_cycle_workflow_id(incident_id, cycle_id),
                task_queue=evidence_q,
            )
            with pytest.raises(WorkflowFailureError):
                await collect_handle.result()

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM domain.evidence WHERE incident_id = %s",
            (str(incident_id),),
        )
        assert int(cur.fetchone()[0]) == 0
