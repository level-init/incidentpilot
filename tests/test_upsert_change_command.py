"""G8: upsert_change_command persists type/service/time/source_ref."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

import incidentpilot_api.commands as api_commands
import incidentpilot_worker.commands as worker_commands
from incidentpilot_shared.changes import change_fingerprint
from incidentpilot_shared.domain import commands as shared_commands
from incidentpilot_shared.domain.commands import upsert_change_command

psycopg = pytest.importorskip("psycopg")


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.change LIMIT 1")
            return True
    except Exception:
        return False


def test_api_and_worker_share_upsert_change_command() -> None:
    assert api_commands.upsert_change_command is shared_commands.upsert_change_command
    assert worker_commands.upsert_change_command is shared_commands.upsert_change_command


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_upsert_change_persists_type_service_time_source_ref() -> None:
    observed = datetime(2024, 7, 1, 15, 30, tzinfo=UTC)
    source_ref = "deploy/checkout@abc123"
    fingerprint = change_fingerprint(
        source="sim",
        change_type="DEPLOYMENT",
        service_key="checkout",
        source_ref=source_ref,
    )
    with psycopg.connect(_dsn()) as conn:
        first = upsert_change_command(
            conn,
            change_type="DEPLOYMENT",
            service_key="checkout",
            observed_at=observed,
            source_ref=source_ref,
            source="sim",
            fingerprint=fingerprint,
            summary="checkout deploy abc123",
            payload={"sha": "abc123"},
            environment="local",
            commit=True,
        )
        assert first.inserted is True
        second = upsert_change_command(
            conn,
            change_type="DEPLOYMENT",
            service_key="checkout",
            observed_at=observed,
            source_ref=source_ref,
            source="sim",
            fingerprint=fingerprint,
            summary="checkout deploy abc123",
            commit=True,
        )
        assert second.inserted is False
        assert second.change_id == first.change_id

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.change_type, s.key, c.observed_at, c.external_ref, c.source
                FROM domain.change c
                JOIN domain.service s ON s.id = c.service_id
                WHERE c.id = %s
                """,
                (str(first.change_id),),
            )
            change_type, service_key, observed_at, external_ref, source = cur.fetchone()
    assert change_type == "DEPLOYMENT"
    assert service_key == "checkout"
    assert observed_at == observed
    assert external_ref == source_ref
    assert source == "sim"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_upsert_change_rejects_bad_type() -> None:
    with psycopg.connect(_dsn()) as conn:
        with pytest.raises(ValueError, match="unsupported change_type"):
            upsert_change_command(
                conn,
                change_type="NOT_A_TYPE",
                service_key="checkout",
                observed_at=datetime.now(tz=UTC),
                source_ref="x",
                source="sim",
                fingerprint="bad",
                summary="nope",
                commit=False,
            )
