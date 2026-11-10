"""J7: validation_window durable timer + ValidationResult; survives worker kill."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("temporalio")
pytest.importorskip("pytest_asyncio")

from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from incidentpilot_shared.incident_workflow import IncidentWorkflowInput  # noqa: E402
from incidentpilot_worker.activities.incident_transitions import (  # noqa: E402
    advance_incident_state,
    load_incident_snapshot,
)
from incidentpilot_worker.activities.validation_window import (  # noqa: E402
    handle_validation_window,
)
from incidentpilot_worker.workflows.incident_workflow import IncidentWorkflow  # noqa: E402
from incidentpilot_worker.workflows.timers import (  # noqa: E402
    TIMER_VALIDATION_WINDOW,
    WorkflowTimerConfig,
)

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="j7-test-act")


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.validation_result LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(not _db_available(), reason="Postgres not reachable"),
    pytest.mark.asyncio,
]


def _seed_validating(incident_id: uuid.UUID, *, error_rate: float) -> uuid.UUID:
    action_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'VALIDATING', 'J7 window', 4)
            """,
            (str(incident_id), f"INC-J7W-{incident_id.hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO domain.action (
                id, incident_id, action_type, current_version, status, proposed_by
            ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, 'EXECUTING', 'system')
            """,
            (str(action_id), str(incident_id)),
        )
        cur.execute(
            """
            INSERT INTO domain.action_version (
                action_id, version, action_type, proposed_by
            ) VALUES (%s, 1, 'ROLLBACK_DEPLOYMENT', 'system')
            """,
            (str(action_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.execution_attempt (
                id, action_id, action_version, attempt_number, state
            ) VALUES (%s, %s, 1, 1, 'SUCCEEDED')
            """,
            (str(attempt_id), str(action_id)),
        )
        cur.execute(
            """
            INSERT INTO domain.evidence (
                id, evidence_key, incident_id, kind, fingerprint, summary,
                payload, provenance, observed_at, producer
            ) VALUES (
                %s, %s, %s, 'ACTION_RESULT', %s, 'rollback ok',
                '{}'::jsonb, '{"layer":"ACTION_OBSERVATION"}'::jsonb, %s,
                'remediation_worker'
            )
            """,
            (
                str(uuid.uuid4()),
                f"EV-ar-{uuid.uuid4().hex[:10]}",
                str(incident_id),
                f"remediation_worker:attempt:{attempt_id}",
                datetime.now(tz=UTC),
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.evidence (
                id, evidence_key, incident_id, kind, fingerprint, summary,
                payload, provenance, observed_at, producer
            ) VALUES (
                %s, %s, %s, 'METRIC', %s, 'checkout error rate',
                %s::jsonb, '{}'::jsonb, %s, 'prometheus_collector'
            )
            """,
            (
                str(uuid.uuid4()),
                f"EV-m-{uuid.uuid4().hex[:10]}",
                str(incident_id),
                f"checkout-error-rate-{uuid.uuid4().hex[:8]}",
                f'{{"value": {error_rate}}}',
                datetime.now(tz=UTC),
            ),
        )
        conn.commit()
    return attempt_id


@pytest.fixture()
def incident_bundle() -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    iid = uuid.uuid4()
    attempt_id = _seed_validating(iid, error_rate=0.01)
    yield iid, attempt_id


def _worker(env: WorkflowEnvironment, task_queue: str) -> Worker:
    return Worker(
        env.client,
        task_queue=task_queue,
        workflows=[IncidentWorkflow],
        activities=[
            load_incident_snapshot,
            advance_incident_state,
            handle_validation_window,
        ],
        activity_executor=_ACTIVITY_EXECUTOR,
    )


@pytest.mark.temporal_d6
async def test_validation_window_recovers(incident_bundle: tuple[uuid.UUID, uuid.UUID]) -> None:
    incident_id, attempt_id = incident_bundle
    task_queue = f"test-j7-{uuid.uuid4().hex[:8]}"
    timers = WorkflowTimerConfig(validation_window_seconds=0.2)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with _worker(env, task_queue):
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_for_validation=True,
                    execution_attempt_id=str(attempt_id),
                    timers=timers,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            result = await handle.result()
            # J8 routes RECOVERED → RESOLVED after ValidationResult.
            assert result == "RESOLVED"
            assert await handle.query(IncidentWorkflow.validation_outcome) == "RECOVERED"
            assert (
                await handle.query(
                    IncidentWorkflow.timer_fire_count, TIMER_VALIDATION_WINDOW
                )
                == 1
            )

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*), min(outcome) FROM domain.validation_result
            WHERE execution_attempt_id = %s
            """,
            (str(attempt_id),),
        )
        count, outcome = cur.fetchone()
        assert count == 1
        assert outcome == "RECOVERED"


async def test_validation_window_survives_worker_kill() -> None:
    incident_id = uuid.uuid4()
    attempt_id = _seed_validating(incident_id, error_rate=0.02)
    task_queue = f"test-j7-kill-{uuid.uuid4().hex[:8]}"
    timers = WorkflowTimerConfig(validation_window_seconds=2)

    async with await WorkflowEnvironment.start_local() as env:
        worker = _worker(env, task_queue)
        worker_task = asyncio.create_task(worker.run())
        try:
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_for_validation=True,
                    execution_attempt_id=str(attempt_id),
                    timers=timers,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            for _ in range(100):
                armed = await handle.query(IncidentWorkflow.timers_armed)
                if TIMER_VALIDATION_WINDOW in armed:
                    break
                await asyncio.sleep(0.05)
            else:
                raise TimeoutError("validation_window was not armed")

            await worker.shutdown()
            await worker_task

            worker2 = _worker(env, task_queue)
            worker2_task = asyncio.create_task(worker2.run())
            try:
                result = await asyncio.wait_for(handle.result(), timeout=20)
                assert result == "RESOLVED"
                assert await handle.query(IncidentWorkflow.validation_outcome) == "RECOVERED"
                assert (
                    await handle.query(
                        IncidentWorkflow.timer_fire_count, TIMER_VALIDATION_WINDOW
                    )
                    == 1
                )
            finally:
                await worker2.shutdown()
                await worker2_task
        finally:
            if not worker_task.done():
                await worker.shutdown()
                await worker_task
