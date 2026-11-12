"""M11: ServiceDependency catalog + incident blast-radius overlay."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "api",
    ROOT / "shared",
    ROOT / "adapters",
):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_shared.domain.dependencies import build_dependency_map  # noqa: E402

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
                cur.execute("SELECT 1 FROM domain.service_dependency LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_m11_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/topology/dependencies" in paths
    assert "/incidents/{incident_id}/dependency-map" in paths
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "DependencyMapOut" in schemas
    props = schemas["DependencyMapOut"]["properties"]
    assert "upstream_keys" in props
    assert "downstream_keys" in props
    assert "propagation_edge_ids" in props


def test_topology_rbac_without_db(client: TestClient) -> None:
    """Denial must not require Postgres (get_conn_with_permission)."""
    res = client.get("/topology/dependencies")
    assert res.status_code in (401, 403)


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0018 not reachable")
def test_catalog_and_cascading_propagation(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}

    topo = client.get("/topology/dependencies", headers=headers)
    assert topo.status_code == 200, topo.text
    body = topo.json()
    keys = {n["key"] for n in body["nodes"]}
    assert {"gateway", "payment", "inventory", "checkout"}.issubset(keys)
    edge_pairs = {(e["from_key"], e["to_key"]) for e in body["edges"]}
    assert ("gateway", "payment") in edge_pairs
    assert ("gateway", "inventory") in edge_pairs

    # Cascading-style incident: payment + inventory linked → gateway downstream.
    create = client.post(
        "/incidents",
        headers=headers,
        json={
            "title": "m11 cascading map",
            "severity": "SEV2",
            "service_key": "payment",
        },
    )
    assert create.status_code == 201, create.text
    iid = create.json()["id"]

    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.incident_service (incident_id, service_id, involvement)
                SELECT %s, s.id, 'suspected'
                FROM domain.service s
                WHERE s.key = 'inventory' AND s.environment = 'local'
                ON CONFLICT DO NOTHING
                """,
                (iid,),
            )
        conn.commit()

        overlay = build_dependency_map(
            conn,
            environment="local",
            linked_keys=["payment", "inventory"],
        )
        assert "gateway" in overlay["downstream_keys"]
        assert set(overlay["linked_service_keys"]) == {"inventory", "payment"}
        assert overlay["propagation_edge_ids"]

    mapped = client.get(
        f"/incidents/{iid}/dependency-map",
        headers=headers,
    )
    assert mapped.status_code == 200, mapped.text
    data = mapped.json()
    assert set(data["linked_service_keys"]) == {"inventory", "payment"}
    assert "gateway" in data["downstream_keys"]
    hot = [e for e in data["edges"] if e["on_propagation_path"]]
    assert any(e["to_key"] == "payment" for e in hot)
    assert any(e["to_key"] == "inventory" for e in hot)

    missing = client.get(
        f"/incidents/{uuid.uuid4()}/dependency-map",
        headers=headers,
    )
    assert missing.status_code == 404
