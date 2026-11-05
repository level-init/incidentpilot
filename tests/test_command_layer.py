"""B7: shared command layer used by API + workers."""

from __future__ import annotations

import ast
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

import incidentpilot_api.commands as api_commands
import incidentpilot_worker.commands as worker_commands
from incidentpilot_shared.domain import commands as shared_commands
from incidentpilot_shared.domain.commands import transition_incident_command
from incidentpilot_shared.domain.transitions import IncidentState, StaleRevisionError

psycopg = pytest.importorskip("psycopg")

ROOT = Path(__file__).resolve().parents[1]


def _dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "incidentpilot")
    password = os.environ.get("IP_APP_PASSWORD", "incidentpilot_app")
    return f"postgresql://ip_app:{password}@{host}:{port}/{db}"


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.incident LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def test_api_and_worker_share_same_command_callables() -> None:
    assert api_commands.transition_incident_command is shared_commands.transition_incident_command
    assert (
        worker_commands.transition_incident_command is shared_commands.transition_incident_command
    )
    assert api_commands.append_evidence_command is shared_commands.append_evidence_command
    assert worker_commands.append_evidence_command is shared_commands.append_evidence_command
    assert api_commands.decide_approval_command is shared_commands.decide_approval_command
    assert worker_commands.reserve_execution_attempt_command is (
        shared_commands.reserve_execution_attempt_command
    )


def test_adapters_have_no_domain_sql() -> None:
    adapters_root = ROOT / "adapters" / "incidentpilot_adapters"
    offenders: list[str] = []
    for path in adapters_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "domain." in text and (
            "INSERT INTO domain." in text
            or "UPDATE domain." in text
            or "DELETE FROM domain." in text
        ):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_worker_commands_module_imports_shared() -> None:
    path = ROOT / "worker" / "incidentpilot_worker" / "commands.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [
        node.module for node in tree.body if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert "incidentpilot_shared.domain.commands" in imports


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_transition_command_applies_revision_check(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'cmd layer', 1)
            """,
            (str(incident_id), f"INC-CMD-{uuid.uuid4().hex[:8]}"),
        )
    conn.commit()

    with psycopg.connect(_dsn()) as c1:
        result = transition_incident_command(
            c1,
            incident_id=incident_id,
            expected_revision=1,
            to_state=IncidentState.INVESTIGATING,
        )
        assert result.new_revision == 2

    with psycopg.connect(_dsn()) as c2, pytest.raises(StaleRevisionError):
        transition_incident_command(
            c2,
            incident_id=incident_id,
            expected_revision=1,
            to_state=IncidentState.DIAGNOSED,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_append_evidence_command(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'ev cmd', 1)
            """,
            (str(incident_id), f"INC-CMD-{uuid.uuid4().hex[:8]}"),
        )
    result = shared_commands.append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="LOG",
        fingerprint=f"fp-{uuid.uuid4().hex}",
        summary="error spike",
        producer="test_producer",
        commit=False,
    )
    assert result.evidence_key.startswith("EV-")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT summary FROM domain.evidence WHERE id = %s",
            (str(result.evidence_id),),
        )
        assert cur.fetchone()[0] == "error spike"
