"""
Aggregation queries: today_counts, daily_totals, last_event_of_each_type.

Time-dependent tests are pinned with `freezer` (pytest-freezer). The
prior version (PR #16) computed `today = datetime.now(UTC).strftime(...)`
at test time; combined with daily_totals's `date('now', '-14 days')`
read from the SQLite clock, the test could race around UTC midnight
(issue #21 worth-fixing). daily_totals now reads its cutoff from
Python's clock too, so freezer covers both halves.
"""

import pytest

from nbio.models import EventCreate
from nbio.repo import (
    create_event,
    daily_totals,
    last_event_of_each_type,
    soft_delete_event,
    today_counts,
)

FROZEN = "2026-05-16T12:00:00Z"
TODAY = "2026-05-16"


@pytest.fixture(autouse=True)
def _freeze(freezer):
    """Pin all tests in this module to a stable "now"."""
    freezer.move_to(FROZEN)
    yield freezer


def _evt(t, idem, occurred_at, dur=None):
    return EventCreate(
        type=t,
        occurred_at=occurred_at,
        feed_duration_min=dur,
        idempotency_key=f"idem-{idem}-pad",
        created_by_device="device-1",
    )


def test_today_counts_zero_when_empty(conn):
    assert today_counts(conn) == {"feed": 0, "wee": 0, "poo": 0}


def test_today_counts_aggregates_today_only(conn):
    create_event(conn, _evt("feed", "i1", f"{TODAY}T03:00:00.000Z"))
    create_event(conn, _evt("feed", "i2", f"{TODAY}T04:00:00.000Z"))
    create_event(conn, _evt("poo", "i3", f"{TODAY}T05:00:00.000Z"))
    create_event(conn, _evt("wee", "i4", "2020-01-01T00:00:00.000Z"))
    counts = today_counts(conn)
    assert counts == {"feed": 2, "wee": 0, "poo": 1}


def test_today_counts_ignores_deleted(conn):
    _, e1, _ = create_event(conn, _evt("feed", "i1", f"{TODAY}T03:00:00.000Z"))
    soft_delete_event(conn, e1["id"])
    assert today_counts(conn)["feed"] == 0


def test_daily_totals_within_window(conn):
    """`days=14` rolls back 14d via a Python-computed cutoff."""
    create_event(conn, _evt("feed", "i1", f"{TODAY}T03:00:00.000Z", dur=20))
    create_event(conn, _evt("feed", "i2", f"{TODAY}T04:00:00.000Z", dur=30))
    create_event(conn, _evt("wee", "i3", f"{TODAY}T05:00:00.000Z"))
    rows = daily_totals(conn, days=14)
    assert len(rows) == 1
    row = rows[0]
    assert row["day"] == TODAY
    assert row["feed"] == 2
    assert row["wee"] == 1
    assert row["poo"] == 0
    assert row["avg_feed_min"] == 25.0


def test_daily_totals_avg_only_set_when_feeds_have_duration(conn):
    create_event(conn, _evt("feed", "i1", f"{TODAY}T03:00:00.000Z", dur=None))
    rows = daily_totals(conn, days=14)
    assert rows[0]["avg_feed_min"] is None


def test_daily_totals_excludes_pre_window(conn):
    create_event(conn, _evt("feed", "i1", "2020-01-01T00:00:00.000Z"))
    assert daily_totals(conn, days=14) == []


def test_daily_totals_excludes_deleted(conn):
    _, e, _ = create_event(conn, _evt("feed", "i1", f"{TODAY}T03:00:00.000Z"))
    soft_delete_event(conn, e["id"])
    assert daily_totals(conn, days=14) == []


def test_daily_totals_includes_event_exactly_at_window_edge(conn):
    """Cutoff is inclusive: an event dated exactly `days` ago counts."""
    edge = "2026-05-02"  # 14 days before FROZEN
    create_event(conn, _evt("feed", "i1", f"{edge}T03:00:00.000Z"))
    rows = daily_totals(conn, days=14)
    assert len(rows) == 1
    assert rows[0]["day"] == edge


def test_daily_totals_excludes_day_before_edge(conn):
    """And one day prior to the cutoff is excluded."""
    pre_edge = "2026-05-01"  # 15 days before FROZEN
    create_event(conn, _evt("feed", "i1", f"{pre_edge}T03:00:00.000Z"))
    assert daily_totals(conn, days=14) == []


def test_last_event_of_each_type_empty(conn):
    assert last_event_of_each_type(conn) == {}


def test_last_event_of_each_type_picks_latest_per_type(conn):
    create_event(conn, _evt("feed", "i1", "2026-05-16T01:00:00.000Z"))
    create_event(conn, _evt("feed", "i2", "2026-05-16T05:00:00.000Z"))
    create_event(conn, _evt("wee", "i3", "2026-05-16T03:00:00.000Z"))
    out = last_event_of_each_type(conn)
    assert set(out) == {"feed", "wee"}
    assert out["feed"]["occurred_at"] == "2026-05-16T05:00:00.000Z"
    assert "poo" not in out


def test_last_event_of_each_type_ignores_deleted(conn):
    _, e, _ = create_event(conn, _evt("feed", "i1", "2026-05-16T03:00:00.000Z"))
    soft_delete_event(conn, e["id"])
    assert last_event_of_each_type(conn) == {}
