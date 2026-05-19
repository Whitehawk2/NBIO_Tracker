"""
repo.growth_* — weight tracking (v1.1.1).

Mirrors the events repo's idempotency + soft-delete + undelete shape.
"""

from __future__ import annotations

import pytest

from nbio.models import GrowthCreate, GrowthPatch
from nbio.repo import (
    fetch_growth,
    fetch_growth_by_idem,
    growth_create,
    growth_latest,
    growth_list,
    growth_patch,
    growth_soft_delete,
    growth_undelete,
)


def _payload(**over):
    base = dict(
        measured_at="2026-05-16",
        weight_g=3420,
        idempotency_key="idem-growth-aa",
        created_by_device="device-test",
    )
    base.update(over)
    return GrowthCreate(**base)


def test_growth_create_happy_path(conn):
    status, row = growth_create(conn, _payload())
    assert status == "created"
    assert row["weight_g"] == 3420
    assert row["measured_at"] == "2026-05-16"
    assert row["id"] is not None


def test_growth_create_idempotent_same_key(conn):
    """Posting the same idempotency_key twice returns 'already_exists'."""
    growth_create(conn, _payload())
    status, row = growth_create(conn, _payload())
    assert status == "already_exists"
    # Only one row inserted total.
    assert len(growth_list(conn)) == 1


def test_growth_create_different_keys_creates_two_rows(conn):
    growth_create(conn, _payload(idempotency_key="idem-growth-1"))
    growth_create(
        conn, _payload(measured_at="2026-05-23", weight_g=3540, idempotency_key="idem-growth-2")
    )
    rows = growth_list(conn)
    assert len(rows) == 2
    assert {r["weight_g"] for r in rows} == {3420, 3540}


def test_growth_list_filters_deleted_by_default(conn):
    _, ev = growth_create(conn, _payload())
    growth_soft_delete(conn, ev["id"])
    assert growth_list(conn) == []
    # include_deleted=True surfaces the row.
    rows = growth_list(conn, include_deleted=True)
    assert len(rows) == 1
    assert rows[0]["deleted_at"] is not None


def test_growth_list_returns_asc_by_measured_at(conn):
    """Chart needs chronological order — ASC by measured_at."""
    growth_create(conn, _payload(measured_at="2026-05-20", idempotency_key="idem-ccc3"))
    growth_create(conn, _payload(measured_at="2026-05-15", idempotency_key="idem-aaa1"))
    growth_create(conn, _payload(measured_at="2026-05-17", idempotency_key="idem-bbb2"))
    rows = growth_list(conn)
    assert [r["measured_at"] for r in rows] == ["2026-05-15", "2026-05-17", "2026-05-20"]


def test_growth_latest_returns_most_recent_non_deleted(conn):
    growth_create(
        conn, _payload(measured_at="2026-05-15", weight_g=3300, idempotency_key="idem-aaa1")
    )
    growth_create(
        conn, _payload(measured_at="2026-05-22", weight_g=3500, idempotency_key="idem-bbb2")
    )
    latest = growth_latest(conn)
    assert latest is not None
    assert latest["weight_g"] == 3500
    assert latest["measured_at"] == "2026-05-22"


def test_growth_latest_none_when_empty(conn):
    assert growth_latest(conn) is None


def test_growth_latest_skips_deleted(conn):
    """A soft-deleted latest row falls through to the previous one."""
    growth_create(
        conn, _payload(measured_at="2026-05-15", weight_g=3300, idempotency_key="idem-aaa1")
    )
    _, b = growth_create(
        conn, _payload(measured_at="2026-05-22", weight_g=3500, idempotency_key="idem-bbb2")
    )
    growth_soft_delete(conn, b["id"])
    latest = growth_latest(conn)
    assert latest is not None
    assert latest["weight_g"] == 3300


def test_growth_patch_changes_weight(conn):
    _, ev = growth_create(conn, _payload())
    updated = growth_patch(conn, ev["id"], GrowthPatch(weight_g=3500))
    assert updated is not None
    assert updated["weight_g"] == 3500
    # measured_at must be unchanged.
    assert updated["measured_at"] == "2026-05-16"


def test_growth_patch_empty_returns_unchanged(conn):
    """An empty PATCH (no fields set) is a no-op."""
    _, ev = growth_create(conn, _payload())
    out = growth_patch(conn, ev["id"], GrowthPatch())
    assert out is not None
    assert out["weight_g"] == 3420


def test_growth_undelete_clears_deleted_at(conn):
    _, ev = growth_create(conn, _payload())
    growth_soft_delete(conn, ev["id"])
    out = growth_undelete(conn, ev["id"])
    assert out is not None
    assert out["deleted_at"] is None
    # And it re-surfaces in the non-deleted list.
    assert len(growth_list(conn)) == 1


def test_fetch_growth_by_idem(conn):
    _, ev = growth_create(conn, _payload(idempotency_key="idem-lookup"))
    found = fetch_growth_by_idem(conn, "idem-lookup")
    assert found is not None
    assert found["id"] == ev["id"]


def test_fetch_growth_returns_none_for_missing(conn):
    assert fetch_growth(conn, 999) is None


def test_growth_weight_check_rejects_typo():
    """Pydantic-layer guard — weight_g > 30000 doesn't validate."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GrowthCreate(
            measured_at="2026-05-16",
            weight_g=34200,
            idempotency_key="idem-typo",
            created_by_device="device-test",
        )


def test_growth_create_round_trips_length_and_head_circ(conn):
    """Even though UI doesn't expose them yet, the fields persist (#55 forward-compat)."""
    _, ev = growth_create(
        conn,
        _payload(
            idempotency_key="idem-full",
            length_mm=540,
            head_circ_mm=380,
        ),
    )
    assert ev["length_mm"] == 540
    assert ev["head_circ_mm"] == 380
