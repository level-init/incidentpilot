"""D3: StaleRevision is non-retryable; stale worker cannot apply N after N+1."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("temporalio")
pytest.importorskip("pytest_asyncio")

from temporalio import workflow  # noqa: E402
from temporalio.client import WorkflowFailureError  # noqa: E402
from temporalio.common import RetryPolicy  # noqa: E402
from temporalio.exceptions import ApplicationError  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from incidentpilot_shared.domain.transitions import IncidentState  # noqa: E402
from incidentpilot_worker.activities.incident_transitions import (  # noqa: E402
    STALE_REVISION_ERROR_TYPE,
    advance_incident_state,
    load_incident_snapshot,
)
from incidentpilot_worker.commands import transition_incident_command  # noqa: E402
from incidentpilot_worker.workflows.incident_workflow import (  # noqa: E402
    IncidentWorkflow,
    IncidentWorkflowInput,
)

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="d3-test-act")


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.incident LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(not _db_available(), reason="Postgres not reachable"),
]


@pytest.fixture()
def incident_id() -> Iterator[uuid.UUID]:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'D3 stale', 1)
            """,
            (str(iid), f"INC-D3-{iid.hex[:8]}"),
        )
        conn.commit()
    yield iid


def _pg_state(incident_id: uuid.UUID) -> tuple[str, int]:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT state, incident_revision FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        row = cur.fetchone()
        assert row is not None
        return str(row[0]), int(row[1])


@workflow.defn
class _StaleOnceWorkflow:
    """Intentionally does not re-query — proves activity StaleRevision is terminal."""

    @workflow.run
    async def run(self, iid: str) -> str:
        await workflow.execute_activity(
            advance_incident_state,
            args=[iid, "INVESTIGATING", 1],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        return "ok"


def test_stale_worker_cannot_apply_n_after_n_plus_1(incident_id: uuid.UUID) -> None:
    """Spike: concurrent writer moves N→N+1; lagging activity with N must not mutate."""
    with psycopg.connect(_dsn()) as conn:
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=1,
            to_state=IncidentState.TRIAGING,
            actor="concurrent-writer",
            commit=True,
        )
    state, rev = _pg_state(incident_id)
    assert state == "TRIAGING"
    assert rev == 2

    with pytest.raises(ApplicationError) as excinfo:
        advance_incident_state(str(incident_id), "INVESTIGATING", expected_revision=1)

    err = excinfo.value
    assert err.type == STALE_REVISION_ERROR_TYPE
    assert err.non_retryable is True

    state_after, rev_after = _pg_state(incident_id)
    assert state_after == "TRIAGING"
    assert rev_after == 2


@pytest.mark.asyncio
async def test_workflow_requeries_and_completes_after_race(
    incident_id: uuid.UUID,
) -> None:
    """Incident already at TRIAGING@2; workflow re-queries and reaches INVESTIGATING."""
    with psycopg.connect(_dsn()) as conn:
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=1,
            to_state=IncidentState.TRIAGING,
            actor="race",
            commit=True,
        )

    task_queue = f"test-d3-{uuid.uuid4().hex[:8]}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[IncidentWorkflow],
            activities=[load_incident_snapshot, advance_incident_state],
            activity_executor=_ACTIVITY_EXECUTOR,
        ):
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(incident_id=str(incident_id)),
                id=f"incident-d3-{incident_id}",
                task_queue=task_queue,
            )
            result = await handle.result()

    assert result == "INVESTIGATING"
    assert _pg_state(incident_id) == ("INVESTIGATING", 3)


@pytest.mark.asyncio
async def test_stale_revision_is_non_retryable_in_temporal(
    incident_id: uuid.UUID,
) -> None:
    with psycopg.connect(_dsn()) as conn:
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=1,
            to_state=IncidentState.TRIAGING,
            actor="race",
            commit=True,
        )

    task_queue = f"test-d3-nr-{uuid.uuid4().hex[:8]}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[_StaleOnceWorkflow],
            activities=[advance_incident_state],
            activity_executor=_ACTIVITY_EXECUTOR,
        ):
            handle = await env.client.start_workflow(
                _StaleOnceWorkflow.run,
                str(incident_id),
                id=f"stale-once-{incident_id}",
                task_queue=task_queue,
            )
            with pytest.raises(WorkflowFailureError) as excinfo:
                await handle.result()

    cause: BaseException | None = excinfo.value.cause
    app: BaseException | None = cause
    while app is not None and not isinstance(app, ApplicationError):
        app = getattr(app, "cause", None)
    assert isinstance(app, ApplicationError)
    assert app.type == STALE_REVISION_ERROR_TYPE
    assert app.non_retryable is True
    assert _pg_state(incident_id) == ("TRIAGING", 2)
