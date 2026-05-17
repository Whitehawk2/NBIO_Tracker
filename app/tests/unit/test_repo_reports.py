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
    create_event(conn, _evt("breast", "i1", f"{TODAY}T03:00:00.000Z"))
    create_event(conn, _evt("breast", "i2", f"{TODAY}T04:00:00.000Z"))
    create_event(conn, _evt("poo", "i3", f"{TODAY}T05:00:00.000Z"))
    create_event(conn, _evt("wee", "i4", "2020-01-01T00:00:00.000Z"))
    counts = today_counts(conn)
    assert counts == {"feed": 2, "wee": 0, "poo": 1}


def test_today_counts_ignores_deleted(conn):
    _, e1, _ = create_event(conn, _evt("breast", "i1", f"{TODAY}T03:00:00.000Z"))
    soft_delete_event(conn, e1["id"])
    assert today_counts(conn)["feed"] == 0


def test_daily_totals_within_window(conn):
    """`days=14` rolls back 14d via a Python-computed cutoff."""
    create_event(conn, _evt("breast", "i1", f"{TODAY}T03:00:00.000Z", dur=20))
    create_event(conn, _evt("breast", "i2", f"{TODAY}T04:00:00.000Z", dur=30))
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
    create_event(conn, _evt("breast", "i1", f"{TODAY}T03:00:00.000Z", dur=None))
    rows = daily_totals(conn, days=14)
    assert rows[0]["avg_feed_min"] is None


def test_daily_totals_excludes_pre_window(conn):
    create_event(conn, _evt("breast", "i1", "2020-01-01T00:00:00.000Z"))
    assert daily_totals(conn, days=14) == []


def test_daily_totals_excludes_deleted(conn):
    _, e, _ = create_event(conn, _evt("breast", "i1", f"{TODAY}T03:00:00.000Z"))
    soft_delete_event(conn, e["id"])
    assert daily_totals(conn, days=14) == []


def test_daily_totals_includes_event_exactly_at_window_edge(conn):
    """Cutoff is inclusive: an event dated exactly `days` ago counts."""
    edge = "2026-05-02"  # 14 days before FROZEN
    create_event(conn, _evt("breast", "i1", f"{edge}T03:00:00.000Z"))
    rows = daily_totals(conn, days=14)
    assert len(rows) == 1
    assert rows[0]["day"] == edge


def test_daily_totals_excludes_day_before_edge(conn):
    """And one day prior to the cutoff is excluded."""
    pre_edge = "2026-05-01"  # 15 days before FROZEN
    create_event(conn, _evt("breast", "i1", f"{pre_edge}T03:00:00.000Z"))
    assert daily_totals(conn, days=14) == []


def test_last_event_of_each_type_empty(conn):
    assert last_event_of_each_type(conn) == {}


def test_last_event_of_each_type_picks_latest_per_type(conn):
    create_event(conn, _evt("breast", "i1", "2026-05-16T01:00:00.000Z"))
    create_event(conn, _evt("breast", "i2", "2026-05-16T05:00:00.000Z"))
    create_event(conn, _evt("wee", "i3", "2026-05-16T03:00:00.000Z"))
    out = last_event_of_each_type(conn)
    assert set(out) == {"feed", "wee"}
    assert out["feed"]["occurred_at"] == "2026-05-16T05:00:00.000Z"
    assert "poo" not in out


def test_last_event_of_each_type_ignores_deleted(conn):
    _, e, _ = create_event(conn, _evt("breast", "i1", "2026-05-16T03:00:00.000Z"))
    soft_delete_event(conn, e["id"])
    assert last_event_of_each_type(conn) == {}


# ---------------------------------------------------------------------------
# Local-tz bucketing (issue #28 finding #1)
#
# User reported: poo logged at 00:44 local BST appeared under "Yesterday" in
# the Last-3-days overview, but correctly under "Today" in the event list.
# Cause: today_counts / daily_totals bucketed by UTC date; the event list
# already converted to local-tz before bucketing.
#
# These tests pin the new local-tz bucketing in repo: events near local
# midnight bucket by the LOCAL date, not UTC.
# ---------------------------------------------------------------------------


def test_today_counts_buckets_event_at_local_midnight_correctly(conn, monkeypatch, freezer):
    """
    BST: an event at UTC 23:30 on day D is local 00:30 on day D+1. With
    local bucketing, the event counts as "today" when "today" = D+1.
    """
    from nbio import config

    monkeypatch.setattr(config.settings, "tz", "Europe/London")
    # Freeze "now" at 2026-05-17 02:00 BST = 2026-05-17 01:00 UTC
    freezer.move_to("2026-05-17T01:00:00Z")

    # Event at local 00:30 BST on 2026-05-17 = UTC 23:30 on 2026-05-16
    create_event(conn, _evt("breast", "midnight", "2026-05-16T23:30:00.000Z"))
    counts = today_counts(conn)
    assert counts["feed"] == 1, (
        f"event at local 00:30 BST should count under TODAY's bucket; got {counts}"
    )


def test_today_counts_buckets_yesterday_event_correctly_in_local_tz(conn, monkeypatch, freezer):
    """Symmetric: an event at local 22:00 yesterday should NOT count as today."""
    from nbio import config

    monkeypatch.setattr(config.settings, "tz", "Europe/London")
    freezer.move_to("2026-05-17T01:00:00Z")  # 02:00 BST today
    # Event at local 22:00 BST on 2026-05-16 = UTC 21:00 on 2026-05-16
    create_event(conn, _evt("breast", "yesterday-late", "2026-05-16T21:00:00.000Z"))
    counts = today_counts(conn)
    assert counts["feed"] == 0


def test_daily_totals_buckets_event_by_local_date(conn, monkeypatch, freezer):
    """
    Same event as above (local 00:30 BST = UTC 23:30 prev day) — should
    appear in daily_totals under the LOCAL date 2026-05-17, not 2026-05-16.
    """
    from nbio import config

    monkeypatch.setattr(config.settings, "tz", "Europe/London")
    freezer.move_to("2026-05-17T02:00:00Z")  # 03:00 BST → plenty of room past local midnight

    create_event(conn, _evt("breast", "boundary", "2026-05-16T23:30:00.000Z"))
    rows = daily_totals(conn, days=14)
    by_day = {r["day"]: r for r in rows}
    assert "2026-05-17" in by_day, (
        f"expected event bucketed under 2026-05-17 (local); got days {list(by_day)}"
    )
    assert by_day["2026-05-17"]["breast"] == 1
    # And NOT under 2026-05-16
    assert "2026-05-16" not in by_day or by_day["2026-05-16"].get("breast", 0) == 0


def test_daily_totals_in_utc_unchanged_when_tz_is_utc(conn, monkeypatch, freezer):
    """Regression: with tz=UTC the bucketing matches the old behaviour."""
    from nbio import config

    monkeypatch.setattr(config.settings, "tz", "UTC")
    freezer.move_to("2026-05-17T02:00:00Z")

    create_event(conn, _evt("breast", "utc-late", "2026-05-16T23:30:00.000Z"))
    rows = daily_totals(conn, days=14)
    by_day = {r["day"]: r for r in rows}
    # UTC → event date = 2026-05-16
    assert "2026-05-16" in by_day
    assert by_day["2026-05-16"]["breast"] == 1


def test_today_counts_in_eastern_us_buckets_morning_utc_under_previous_day(
    conn, monkeypatch, freezer
):
    """
    Negative-offset side: America/New_York is UTC-4 in May. An event at
    UTC 03:00 on day D is local 23:00 on day D-1. With local bucketing,
    that event is YESTERDAY in local terms.
    """
    from nbio import config

    monkeypatch.setattr(config.settings, "tz", "America/New_York")
    # Freeze "now" at 2026-05-16 12:00 UTC = 2026-05-16 08:00 EDT
    freezer.move_to("2026-05-16T12:00:00Z")

    # Event at UTC 03:00 = local 23:00 on 2026-05-15 (yesterday in EDT)
    create_event(conn, _evt("breast", "neg-tz", "2026-05-16T03:00:00.000Z"))
    counts = today_counts(conn)
    assert counts["feed"] == 0, (
        f"event at local 23:00 yesterday EDT should NOT count as today; got {counts}"
    )
