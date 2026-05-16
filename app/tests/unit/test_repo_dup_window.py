"""±2-min duplicate window query — boundary + delta_seconds correctness."""

import pytest

from nbio.models import EventCreate
from nbio.repo import create_event, find_duplicate_in_window


def _payload(**over):
    base = {
        "type": "feed",
        "occurred_at": "2026-05-16T03:00:00.000Z",
        "idempotency_key": "idem-default",
        "created_by_device": "device-1",
    }
    base.update(over)
    return EventCreate(**base)


def test_within_window_flagged(conn):
    """Two same-type events 60s apart → second sees the first as dup."""
    _, first, _ = create_event(
        conn, _payload(idempotency_key="idem-i1-pad", occurred_at="2026-05-16T03:00:00.000Z")
    )
    status, second, dup = create_event(
        conn, _payload(idempotency_key="idem-i2-pad", occurred_at="2026-05-16T03:01:00.000Z")
    )
    assert status == "created_possible_duplicate"
    assert dup is not None
    assert dup["id"] == first["id"]
    assert abs(dup["delta_seconds"]) == 60


def test_outside_window_not_flagged(conn):
    """3 min apart → no duplicate."""
    create_event(
        conn, _payload(idempotency_key="idem-i1-pad", occurred_at="2026-05-16T03:00:00.000Z")
    )
    status, _, dup = create_event(
        conn, _payload(idempotency_key="idem-i2-pad", occurred_at="2026-05-16T03:03:00.000Z")
    )
    assert status == "created"
    assert dup is None


def test_exactly_at_boundary_flagged(conn):
    """At exactly the configured window (120s) — flagged per `<=` predicate."""
    create_event(
        conn, _payload(idempotency_key="idem-i1-pad", occurred_at="2026-05-16T03:00:00.000Z")
    )
    status, _, dup = create_event(
        conn, _payload(idempotency_key="idem-i2-pad", occurred_at="2026-05-16T03:02:00.000Z")
    )
    assert status == "created_possible_duplicate"
    assert dup is not None
    assert abs(dup["delta_seconds"]) == 120


def test_one_second_past_boundary_not_flagged(conn):
    create_event(
        conn, _payload(idempotency_key="idem-i1-pad", occurred_at="2026-05-16T03:00:00.000Z")
    )
    status, _, _ = create_event(
        conn, _payload(idempotency_key="idem-i2-pad", occurred_at="2026-05-16T03:02:01.000Z")
    )
    assert status == "created"


def test_different_type_does_not_clash(conn):
    """Feed at T, poo at T+30s → no dup (different types)."""
    create_event(
        conn,
        _payload(
            type="feed",
            idempotency_key="idem-i1-pad",
            occurred_at="2026-05-16T03:00:00.000Z",
        ),
    )
    status, _, dup = create_event(
        conn,
        _payload(
            type="poo",
            idempotency_key="idem-i2-pad",
            occurred_at="2026-05-16T03:00:30.000Z",
        ),
    )
    assert status == "created"
    assert dup is None


def test_deleted_events_dont_count(conn):
    """A soft-deleted event in the window is invisible to the dup query."""
    from nbio.repo import soft_delete_event

    _, first, _ = create_event(
        conn, _payload(idempotency_key="idem-i1-pad", occurred_at="2026-05-16T03:00:00.000Z")
    )
    soft_delete_event(conn, first["id"])
    status, _, dup = create_event(
        conn, _payload(idempotency_key="idem-i2-pad", occurred_at="2026-05-16T03:01:00.000Z")
    )
    assert status == "created"
    assert dup is None


def test_skip_dup_check_suppresses_flag(conn):
    create_event(
        conn, _payload(idempotency_key="idem-i1-pad", occurred_at="2026-05-16T03:00:00.000Z")
    )
    status, _, dup = create_event(
        conn,
        _payload(
            idempotency_key="idem-i2-pad",
            occurred_at="2026-05-16T03:00:30.000Z",
            skip_dup_check=True,
        ),
    )
    assert status == "created"
    assert dup is None


def test_find_duplicate_in_window_excludes_own_id(conn):
    """When checking, the candidate row itself is excluded via `id != ?`."""
    _, first, _ = create_event(
        conn, _payload(idempotency_key="idem-i1-pad", occurred_at="2026-05-16T03:00:00.000Z")
    )
    # Calling with own_id = first's id should return None
    found = find_duplicate_in_window(conn, 1, "feed", first["occurred_at"], first["id"])
    assert found is None


def test_window_picks_closest(conn):
    """Multiple candidates → ORDER BY abs(delta) ASC picks the nearest."""
    create_event(
        conn, _payload(idempotency_key="idem-i1-pad", occurred_at="2026-05-16T03:00:00.000Z")
    )
    create_event(
        conn, _payload(idempotency_key="idem-i2-pad", occurred_at="2026-05-16T03:00:30.000Z")
    )
    status, _, dup = create_event(
        conn, _payload(idempotency_key="idem-i3-pad", occurred_at="2026-05-16T03:00:35.000Z")
    )
    assert status == "created_possible_duplicate"
    assert dup["occurred_at"] == "2026-05-16T03:00:30.000Z"


def test_window_setting_respected(conn, monkeypatch):
    """Adjusting `settings.dup_window_seconds` changes the cutoff."""
    from nbio import config

    monkeypatch.setattr(config.settings, "dup_window_seconds", 30)
    create_event(
        conn, _payload(idempotency_key="idem-i1-pad", occurred_at="2026-05-16T03:00:00.000Z")
    )
    # 45s apart, now outside the 30s window
    status, _, dup = create_event(
        conn, _payload(idempotency_key="idem-i2-pad", occurred_at="2026-05-16T03:00:45.000Z")
    )
    assert status == "created"


@pytest.mark.parametrize(
    "delta_s,expected_status",
    [
        (0, "created_possible_duplicate"),
        (59, "created_possible_duplicate"),
        (119, "created_possible_duplicate"),
        (120, "created_possible_duplicate"),
        (121, "created"),
    ],
)
def test_boundary_param(conn, delta_s, expected_status):
    create_event(
        conn, _payload(idempotency_key="idem-anchor", occurred_at="2026-05-16T03:00:00.000Z")
    )
    iso = (
        f"2026-05-16T03:{delta_s // 60:02d}:{delta_s % 60:02d}.000Z"
        if delta_s < 120
        else "2026-05-16T03:02:00.000Z"
        if delta_s == 120
        else "2026-05-16T03:02:01.000Z"
    )
    # Use distinct idem each parameterization
    status, _, _ = create_event(
        conn, _payload(idempotency_key=f"idem-p-{delta_s:04d}", occurred_at=iso)
    )
    assert status == expected_status
