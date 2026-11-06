"""G10: INVESTIGATING → collect → citable Evidence (no planted GT)."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from unittest.mock import patch

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("temporalio")
pytest.importorskip("pytest_asyncio")

from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from incidentpilot_adapters.telemetry.loki import LokiQueryResult  # noqa: E402
from incidentpilot_adapters.telemetry.prometheus import PrometheusQueryResult  # noqa: E402
from incidentpilot_adapters.telemetry.tempo import TempoQueryResult  # noqa: E402
from incidentpilot_shared.incident_workflow import (  # noqa: E402
    ensure_incident_workflow_started,
    incident_workflow_id,
)
from incidentpilot_worker.activities.collect_cycle import (  # noqa: E402
    run_collect_cycle,
    validate_collect_job_scope,
)
from incidentpilot_worker.activities.collector_trigger import kickoff_collect_cycle  # noqa: E402
from incidentpilot_worker.activities.incident_transitions import (  # noqa: E402
    advance_incident_state,
    load_incident_snapshot,
)
from incidentpilot_worker.workflows.collect_cycle import CollectCycleWorkflow  # noqa: E402
from incidentpilot_worker.workflows.incident_workflow import IncidentWorkflow  # noqa: E402

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="g10-test-act")


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
def incident_id() -> uuid.UUID:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G10 loop', 1)
            """,
            (str(iid), f"INC-G10-{iid.hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO domain.service (key, display_name, environment)
            VALUES ('payment', 'payment', 'local')
            ON CONFLICT (key, environment) DO UPDATE SET display_name = EXCLUDED.display_name
            RETURNING id
            """
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
    return iid


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
            streams=[{"stream": {"job": "payment"}, "values": [["1", "error"]]}],
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
            traces=[{"traceID": "g10", "rootServiceName": "payment", "durationMs": 20}],
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
@pytest.mark.asyncio
async def test_natural_path_yields_citable_evidence_including_deployment(
    incident_id: uuid.UUID,
) -> None:
    general_q = f"test-g10-gen-{uuid.uuid4().hex[:8]}"
    evidence_q = f"test-g10-ev-{uuid.uuid4().hex[:8]}"
    os.environ["COLLECT_CYCLE_TASK_QUEUE"] = evidence_q
    try:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with (
                Worker(
                    env.client,
                    task_queue=general_q,
                    workflows=[IncidentWorkflow],
                    activities=[
                        load_incident_snapshot,
                        advance_incident_state,
                        kickoff_collect_cycle,
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
                    started = await ensure_incident_workflow_started(
                        env.client,
                        incident_id,
                        task_queue=general_q,
                    )
                    assert started is True
                    handle = env.client.get_workflow_handle(incident_workflow_id(incident_id))
                    assert await handle.result() == "INVESTIGATING"
                    count = await handle.query(IncidentWorkflow.evidence_updated_count)
                    assert count == 1
                    last = await handle.query(IncidentWorkflow.last_evidence_updated)
                    assert last is not None
                    assert last.evidence_ids
    finally:
        os.environ.pop("COLLECT_CYCLE_TASK_QUEUE", None)

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT kind, evidence_key, producer
            FROM domain.evidence
            WHERE incident_id = %s
            ORDER BY kind
            """,
            (str(incident_id),),
        )
        rows = cur.fetchall()
        kinds = {r[0] for r in rows}
        assert "CHANGE" in kinds
        assert kinds & {"METRIC", "LOG", "TRACE"}
        assert all(str(r[1]).startswith("EV-") for r in rows)

        cur.execute(
            """
            SELECT payload->>'change_type', payload->>'service_key'
            FROM domain.evidence
            WHERE incident_id = %s AND kind = 'CHANGE'
              AND payload->>'change_type' = 'DEPLOYMENT'
              AND payload->>'service_key' = 'payment'
            """,
            (str(incident_id),),
        )
        deploy = cur.fetchone()
        assert deploy is not None
        assert deploy[0] == "DEPLOYMENT"
        assert deploy[1] == "payment"

        cur.execute(
            """
            SELECT count(*) FROM domain.evidence_projection ep
            JOIN domain.evidence e ON e.id = ep.evidence_id
            WHERE e.incident_id = %s AND ep.status = 'READY'
            """,
            (str(incident_id),),
        )
        assert int(cur.fetchone()[0]) >= 1
