"""Sim scenario change catalog (G9) — ops-looking records, no GroundTruth labels.

E5 injectors remain symptom-only; this catalog is the change-intelligence view
collectors read. Types cover the eight scenario classes without a GitHub clone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from incidentpilot_shared.changes import NormalizedChange, change_fingerprint

_SOURCE = "sim"


def _change(
    *,
    change_type: str,
    service_key: str,
    source_ref: str,
    summary: str,
    observed_at: datetime,
    payload: dict[str, Any] | None = None,
) -> NormalizedChange:
    return NormalizedChange(
        change_type=change_type,
        service_key=service_key,
        observed_at=observed_at,
        source_ref=source_ref,
        source=_SOURCE,
        fingerprint=change_fingerprint(
            source=_SOURCE,
            change_type=change_type,
            service_key=service_key,
            source_ref=source_ref,
        ),
        summary=summary,
        payload=payload or {},
        provenance={"catalog": "sim_scenario_changes.v1"},
    )


def scenario_changes_at(observed_at: datetime) -> list[NormalizedChange]:
    """Build the eight-scenario change set stamped at ``observed_at``."""
    return [
        # bad_deploy (payment) — AC: DEPLOYMENT + supporting commit/PR
        _change(
            change_type="DEPLOYMENT",
            service_key="payment",
            source_ref="sim:deploy:payment:v1.4.2",
            summary="payment deploy v1.4.2",
            observed_at=observed_at,
            payload={"version": "1.4.2", "sha": "deadbeef01", "service": "payment"},
        ),
        _change(
            change_type="COMMIT",
            service_key="payment",
            source_ref="sim:commit:payment:deadbeef01",
            summary="payment: raise charge timeout defaults",
            observed_at=observed_at,
            payload={"sha": "deadbeef01"},
        ),
        _change(
            change_type="PULL_REQUEST",
            service_key="payment",
            source_ref="sim:pr:payment:42",
            summary="PR #42 payment deploy prep",
            observed_at=observed_at,
            payload={"pr": 42, "sha": "deadbeef01"},
        ),
        # bad_config / flag (auth)
        _change(
            change_type="FEATURE_FLAG",
            service_key="auth",
            source_ref="sim:flag:auth:strict_jwt",
            summary="auth flag strict_jwt=true",
            observed_at=observed_at,
            payload={"flag": "strict_jwt", "value": True},
        ),
        _change(
            change_type="CONFIG",
            service_key="auth",
            source_ref="sim:config:auth:jwt_skew",
            summary="auth config jwt_skew_seconds=0",
            observed_at=observed_at,
            payload={"key": "jwt_skew_seconds", "value": 0},
        ),
        # dependency_timeout / cascading (payment already covered)
        # db_exhaustion (inventory)
        _change(
            change_type="CONFIG",
            service_key="inventory",
            source_ref="sim:config:inventory:pool_size",
            summary="inventory db pool_size=4",
            observed_at=observed_at,
            payload={"key": "pool_size", "value": 4},
        ),
        # memory_leak / cpu (checkout)
        _change(
            change_type="DEPLOYMENT",
            service_key="checkout",
            source_ref="sim:deploy:checkout:v2.1.0",
            summary="checkout deploy v2.1.0",
            observed_at=observed_at,
            payload={"version": "2.1.0", "sha": "cafebabe02"},
        ),
        _change(
            change_type="COMMIT",
            service_key="checkout",
            source_ref="sim:commit:checkout:cafebabe02",
            summary="checkout: cache cart lines in-process",
            observed_at=observed_at,
            payload={"sha": "cafebabe02"},
        ),
        # queue_backlog (notification)
        _change(
            change_type="SCALE",
            service_key="notification",
            source_ref="sim:scale:notification:replicas-1",
            summary="notification scale replicas=1",
            observed_at=observed_at,
            payload={"replicas": 1},
        ),
        # cascading / shared commit on inventory
        _change(
            change_type="COMMIT",
            service_key="inventory",
            source_ref="sim:commit:inventory:feedface03",
            summary="inventory: tighten reservation lock",
            observed_at=observed_at,
            payload={"sha": "feedface03"},
        ),
    ]
