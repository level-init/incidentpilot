"""ServiceDependency catalog helpers (M11) — Postgres graph, not Neo4j."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row


@dataclass(frozen=True)
class DependencyEdge:
    edge_id: UUID
    from_key: str
    to_key: str
    dependency_type: str
    environment: str
    discovery_source: str
    confidence_tier: str


@dataclass(frozen=True)
class ServiceNode:
    service_id: UUID
    key: str
    display_name: str
    environment: str
    criticality: str


def list_services(
    conn: Connection, *, environment: str = "local"
) -> list[ServiceNode]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, key, display_name, environment, criticality
            FROM domain.service
            WHERE environment = %s
            ORDER BY key
            """,
            (environment,),
        )
        rows = cur.fetchall()
    return [
        ServiceNode(
            service_id=r["id"],
            key=str(r["key"]),
            display_name=str(r["display_name"]),
            environment=str(r["environment"]),
            criticality=str(r["criticality"]),
        )
        for r in rows
    ]


def list_dependency_edges(
    conn: Connection, *, environment: str = "local"
) -> list[DependencyEdge]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT d.id, f.key AS from_key, t.key AS to_key,
                   d.dependency_type, d.environment,
                   d.discovery_source, d.confidence_tier
            FROM domain.service_dependency d
            JOIN domain.service f ON f.id = d.from_service_id
            JOIN domain.service t ON t.id = d.to_service_id
            WHERE d.environment = %s
              AND (d.valid_to IS NULL OR d.valid_to > now())
            ORDER BY f.key, t.key
            """,
            (environment,),
        )
        rows = cur.fetchall()
    return [
        DependencyEdge(
            edge_id=r["id"],
            from_key=str(r["from_key"]),
            to_key=str(r["to_key"]),
            dependency_type=str(r["dependency_type"]),
            environment=str(r["environment"]),
            discovery_source=str(r["discovery_source"]),
            confidence_tier=str(r["confidence_tier"]),
        )
        for r in rows
    ]


def incident_service_keys(conn: Connection, *, incident_id: UUID) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.key
            FROM domain.incident_service isv
            JOIN domain.service s ON s.id = isv.service_id
            WHERE isv.incident_id = %s
            ORDER BY s.key
            """,
            (str(incident_id),),
        )
        return [str(r[0]) for r in cur.fetchall()]


def build_dependency_map(
    conn: Connection,
    *,
    environment: str = "local",
    linked_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Catalog nodes/edges plus optional incident overlay (1-hop propagation)."""
    nodes = list_services(conn, environment=environment)
    edges = list_dependency_edges(conn, environment=environment)
    linked = set(linked_keys or [])

    upstream: set[str] = set()  # callees of linked (what linked depends on)
    downstream: set[str] = set()  # callers of linked
    prop_edge_ids: list[str] = []

    for e in edges:
        if e.from_key in linked:
            upstream.add(e.to_key)
            prop_edge_ids.append(str(e.edge_id))
        if e.to_key in linked:
            downstream.add(e.from_key)
            prop_edge_ids.append(str(e.edge_id))

    # Deduplicate while preserving order
    seen: set[str] = set()
    prop_unique: list[str] = []
    for eid in prop_edge_ids:
        if eid not in seen:
            seen.add(eid)
            prop_unique.append(eid)

    return {
        "environment": environment,
        "nodes": [
            {
                "service_id": str(n.service_id),
                "key": n.key,
                "display_name": n.display_name,
                "environment": n.environment,
                "criticality": n.criticality,
                "linked": n.key in linked,
                "upstream": n.key in upstream,
                "downstream": n.key in downstream,
            }
            for n in nodes
        ],
        "edges": [
            {
                "edge_id": str(e.edge_id),
                "from_key": e.from_key,
                "to_key": e.to_key,
                "dependency_type": e.dependency_type,
                "discovery_source": e.discovery_source,
                "confidence_tier": e.confidence_tier,
                "on_propagation_path": str(e.edge_id) in seen,
            }
            for e in edges
        ],
        "linked_service_keys": sorted(linked),
        "upstream_keys": sorted(upstream),
        "downstream_keys": sorted(downstream),
        "propagation_edge_ids": prop_unique,
    }
