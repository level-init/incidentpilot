"""G5: RAW blob upload + provenance fallback (no fake HIGH without blob_uri)."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "shared", ROOT / "worker", ROOT / "adapters"):
    sys.path.insert(0, str(p))

from incidentpilot_adapters.blob import FailingBlobStore, MemoryBlobStore  # noqa: E402
from incidentpilot_adapters.telemetry.prometheus import PrometheusQueryResult  # noqa: E402
from incidentpilot_shared.domain.commands import append_evidence_command  # noqa: E402
from incidentpilot_shared.evidence_raw import (  # noqa: E402
    InvalidRawProvenance,
    assert_raw_high_requires_blob,
    plan_raw_evidence_write,
)
from incidentpilot_worker.collectors import collect_metrics_for_incident  # noqa: E402

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
                cur.execute("SELECT 1 FROM domain.evidence LIMIT 1")
            return True
    except Exception:
        return False


def _incident() -> uuid.UUID:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G5 blob', 1)
            """,
            (str(iid), f"INC-G5-{iid.hex[:8]}"),
        )
        conn.commit()
    return iid


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


def test_plan_upload_ok_is_high_with_blob_uri() -> None:
    store = MemoryBlobStore()
    plan = plan_raw_evidence_write(
        payload={"series": [1]},
        source="prometheus",
        external_ref={"window": {"start": 1, "end": 2}},
        blob_store=store,
        object_key="incidents/x/prometheus_collector/fp.json",
    )
    assert plan.blob_uri is not None
    assert plan.blob_uri.startswith("s3://incidentpilot-evidence/")
    assert plan.provenance["quality"] == "HIGH"
    assert plan.provenance["layer"] == "RAW"
    assert plan.provenance["blob_status"] == "UPLOADED"
    assert "content_hash" in plan.provenance
    assert plan.blob_uri in store.objects


def test_plan_minio_down_is_medium_not_high() -> None:
    plan = plan_raw_evidence_write(
        payload={"series": [1]},
        source="prometheus",
        external_ref={"query": "up"},
        blob_store=FailingBlobStore("minio down"),
        object_key="incidents/x/fp.json",
    )
    assert plan.blob_uri is None
    assert plan.provenance["quality"] == "MEDIUM"
    assert plan.provenance["layer"] == "RAW"
    assert plan.provenance["blob_status"] == "UPLOAD_FAILED"
    assert plan.provenance["external_ref"] == {"query": "up"}
    assert "content_hash" in plan.provenance


def test_plan_store_unavailable_alternate_provenance() -> None:
    plan = plan_raw_evidence_write(
        payload={"x": 1},
        source="loki",
        external_ref={"window": {"start": 0, "end": 1}},
        blob_store=None,
        object_key="k.json",
    )
    assert plan.blob_uri is None
    assert plan.provenance["quality"] == "MEDIUM"
    assert plan.provenance["blob_status"] == "STORE_UNAVAILABLE"
    assert plan.provenance["external_ref"]["window"]["end"] == 1


def test_assert_rejects_fake_high_raw() -> None:
    with pytest.raises(InvalidRawProvenance):
        assert_raw_high_requires_blob(
            blob_uri=None,
            provenance={"layer": "RAW", "quality": "HIGH"},
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_append_rejects_fake_high_raw() -> None:
    iid = _incident()
    with psycopg.connect(_dsn()) as db:
        with pytest.raises(InvalidRawProvenance):
            append_evidence_command(
                db,
                incident_id=iid,
                kind="METRIC",
                fingerprint=f"fake-high-{uuid.uuid4().hex[:8]}",
                summary="should fail",
                producer="prometheus_collector",
                payload={"v": 1},
                provenance={"layer": "RAW", "quality": "HIGH"},
                blob_uri=None,
                commit=False,
            )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_collect_minio_down_writes_medium_without_blob_uri() -> None:
    iid = _incident()
    start, end = 1_700_200_000.0, 1_700_200_600.0
    result = collect_metrics_for_incident(
        incident_id=iid,
        start=start,
        end=end,
        query="up",
        client=_FakeProm(),  # type: ignore[arg-type]
        blob_store=FailingBlobStore("fault inject MinIO"),
    )
    assert result.inserted is True
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT blob_uri, provenance->>'quality', provenance->>'layer',
                   provenance->>'blob_status', provenance ? 'content_hash',
                   provenance->'external_ref' ? 'query'
            FROM domain.evidence WHERE id = %s
            """,
            (str(result.evidence_id),),
        )
        blob_uri, quality, layer, status, has_hash, has_ref = cur.fetchone()
    assert blob_uri is None
    assert quality == "MEDIUM"
    assert layer == "RAW"
    assert status == "UPLOAD_FAILED"
    assert has_hash is True
    assert has_ref is True


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_collect_upload_ok_is_high_with_blob_uri() -> None:
    iid = _incident()
    store = MemoryBlobStore()
    start, end = 1_700_210_000.0, 1_700_210_600.0
    result = collect_metrics_for_incident(
        incident_id=iid,
        start=start,
        end=end,
        query="up",
        client=_FakeProm(),  # type: ignore[arg-type]
        blob_store=store,
    )
    assert result.inserted is True
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT blob_uri, provenance->>'quality', provenance->>'blob_status'
            FROM domain.evidence WHERE id = %s
            """,
            (str(result.evidence_id),),
        )
        blob_uri, quality, status = cur.fetchone()
    assert blob_uri is not None
    assert blob_uri.startswith("s3://")
    assert quality == "HIGH"
    assert status == "UPLOADED"
    assert blob_uri in store.objects
