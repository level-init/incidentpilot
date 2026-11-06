"""G8: ChangeSource port is read-only; MemoryChangeSource filters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import get_type_hints

import pytest

from incidentpilot_adapters.changes import ChangeSource, MemoryChangeSource
from incidentpilot_shared.changes import NormalizedChange, change_fingerprint


def _change(
    *,
    source_ref: str,
    service: str = "checkout",
    change_type: str = "DEPLOYMENT",
    when: datetime | None = None,
    source: str = "memory",
) -> NormalizedChange:
    observed = when or datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    fp = change_fingerprint(
        source=source,
        change_type=change_type,
        service_key=service,
        source_ref=source_ref,
    )
    return NormalizedChange(
        change_type=change_type,
        service_key=service,
        observed_at=observed,
        source_ref=source_ref,
        source=source,
        fingerprint=fp,
        summary=f"{change_type} {source_ref}",
        payload={"ref": source_ref},
    )


def test_change_source_protocol_has_no_mutate_methods() -> None:
    hints = get_type_hints(ChangeSource)
    assert "name" in hints or hasattr(ChangeSource, "name")
    allowed = {"list_changes", "fetch_change"}
    # Protocol members that look callable
    members = {
        name
        for name, value in vars(ChangeSource).items()
        if not name.startswith("_") and callable(value)
    }
    assert members == allowed
    forbidden = {
        "deploy",
        "rollback",
        "mutate",
        "apply",
        "create",
        "scale",
        "delete",
        "update",
    }
    assert not (members & forbidden)
    assert not any(hasattr(MemoryChangeSource, name) and name in forbidden for name in forbidden)


def test_memory_change_source_filters_and_fetch() -> None:
    t0 = datetime(2024, 6, 1, tzinfo=UTC)
    src = MemoryChangeSource(
        changes=[
            _change(source_ref="deploy-1", service="checkout", when=t0),
            _change(source_ref="deploy-2", service="payment", when=t0 + timedelta(hours=1)),
            _change(
                source_ref="commit-1",
                service="checkout",
                change_type="COMMIT",
                when=t0 + timedelta(hours=2),
            ),
        ]
    )
    assert len(src.list_changes(service="checkout")) == 2
    assert len(src.list_changes(since=t0 + timedelta(minutes=30))) == 2
    assert len(src.list_changes(until=t0 + timedelta(minutes=30))) == 1
    found = src.fetch_change("deploy-2")
    assert found is not None
    assert found.service_key == "payment"
    assert src.fetch_change("missing") is None


def test_normalized_change_rejects_bad_type() -> None:
    with pytest.raises(ValueError, match="unsupported change_type"):
        _change(source_ref="x", change_type="NOT_A_TYPE")


def test_change_fingerprint_stable() -> None:
    a = change_fingerprint(
        source="github",
        change_type="DEPLOYMENT",
        service_key="checkout",
        source_ref="sha-abc",
    )
    b = change_fingerprint(
        source="github",
        change_type="DEPLOYMENT",
        service_key="checkout",
        source_ref="sha-abc",
    )
    assert a == b
    assert a.startswith("chg:github:")
