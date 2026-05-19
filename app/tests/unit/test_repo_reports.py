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


def _evt(t, idem, occurred_at, dur=None, brand=None, volume_ml=None):
    return EventCreate(
        type=t,
        occurred_at=occurred_at,
        feed_duration_min=dur,
        formula_brand=brand,
        formula_volume_ml=volume_ml,
        idempotency_key=f"idem-{idem}-pad",
        created_by_device="device-1",
    )


def test_today_counts_zero_when_empty(conn):
    assert today_counts(conn) == {
        "feed": 0,
        "wee": 0,
        "poo": 0,
        "vitd": 0,
        "tummy_time": 0,
        "formula_ml": 0,
    }


def test_today_counts_aggregates_formula_volume_ml(conn):
    """
    Daily formula intake is a first-class glance metric — `today_counts`
    must include the SUM of `formula_volume_ml` across today's formula
    feeds under the `formula_ml` key. Breast feeds and rows without a
    volume don't contribute.
    """
    create_event(
        conn, _evt("formula", "f1", f"{TODAY}T03:00:00.000Z", brand="Materna", volume_ml=120)
    )
    create_event(
        conn, _evt("formula", "f2", f"{TODAY}T06:00:00.000Z", brand="Materna", volume_ml=90)
    )
    create_event(conn, _evt("breast", "b1", f"{TODAY}T09:00:00.000Z"))
    # An older formula must NOT contribute.
    create_event(
        conn, _evt("formula", "f3", "2026-05-15T03:00:00.000Z", brand="Materna", volume_ml=200)
    )
    counts = today_counts(conn)
    assert counts["formula_ml"] == 210
    assert counts["feed"] == 3  # 2 formula + 1 breast


def test_today_counts_formula_volume_zero_when_volume_null(conn):
    """A formula row without a volume_ml entry must not break aggregation."""
    create_event(conn, _evt("formula", "f1", f"{TODAY}T03:00:00.000Z", brand="Materna"))
    counts = today_counts(conn)
    assert counts["formula_ml"] == 0
    assert counts["feed"] == 1


def test_today_counts_aggregates_today_only(conn):
    create_event(conn, _evt("breast", "i1", f"{TODAY}T03:00:00.000Z"))
    create_event(conn, _evt("breast", "i2", f"{TODAY}T04:00:00.000Z"))
    create_event(conn, _evt("poo", "i3", f"{TODAY}T05:00:00.000Z"))
    create_event(conn, _evt("wee", "i4", "2020-01-01T00:00:00.000Z"))
    counts = today_counts(conn)
    assert counts == {
        "feed": 2,
        "wee": 0,
        "poo": 1,
        "vitd": 0,
        "tummy_time": 0,
        "formula_ml": 0,
    }


def test_today_counts_includes_vitd_key(conn):
    """`vitd` key is always present in today_counts (0 when none today)."""
    counts = today_counts(conn)
    assert "vitd" in counts
    assert counts["vitd"] == 0


def test_today_counts_counts_todays_vitd_events(conn):
    create_event(conn, _evt("vitd", "v1", f"{TODAY}T09:00:00.000Z"))
    counts = today_counts(conn)
    assert counts["vitd"] == 1


def test_today_counts_vitd_excludes_other_days(conn):
    """A vitd event yesterday doesn't count for today."""
    create_event(conn, _evt("vitd", "v1", "2026-05-15T09:00:00.000Z"))
    counts = today_counts(conn)
    assert counts["vitd"] == 0


def test_today_counts_includes_tummy_time_key(conn):
    """`tummy_time` key is always present in today_counts (0 when none today)."""
    counts = today_counts(conn)
    assert "tummy_time" in counts
    assert counts["tummy_time"] == 0


def test_today_counts_counts_todays_tummy_sessions(conn):
    """Multiple tummy sessions today aggregate as a session count."""
    create_event(conn, _evt("tummy_time", "tt1", f"{TODAY}T08:00:00.000Z", dur=5))
    create_event(conn, _evt("tummy_time", "tt2", f"{TODAY}T11:00:00.000Z", dur=3))
    counts = today_counts(conn)
    assert counts["tummy_time"] == 2
    # Tummy sessions don't bump the feed count.
    assert counts["feed"] == 0


def test_today_counts_tummy_excludes_other_days(conn):
    """A tummy_time event yesterday doesn't count for today."""
    create_event(conn, _evt("tummy_time", "tt1", "2026-05-15T08:00:00.000Z", dur=5))
    assert today_counts(conn)["tummy_time"] == 0


def test_today_totals_zero_when_empty(conn):
    """today_totals returns zero minutes when no tummy_time events exist."""
    from nbio.repo import today_totals

    assert today_totals(conn) == {"tummy_time_min": 0}


def test_today_totals_sums_tummy_minutes_today(conn):
    """today_totals sums feed_duration_min across today's tummy_time events."""
    from nbio.repo import today_totals

    create_event(conn, _evt("tummy_time", "tt1", f"{TODAY}T08:00:00.000Z", dur=5))
    create_event(conn, _evt("tummy_time", "tt2", f"{TODAY}T11:00:00.000Z", dur=3))
    # A tummy event yesterday must NOT bleed into today's total.
    create_event(conn, _evt("tummy_time", "tt3", "2026-05-15T08:00:00.000Z", dur=10))
    assert today_totals(conn) == {"tummy_time_min": 8}


def test_today_totals_excludes_deleted(conn):
    """Soft-deleted tummy events don't contribute to today_totals."""
    from nbio.repo import today_totals

    _, ev, _ = create_event(conn, _evt("tummy_time", "tt1", f"{TODAY}T08:00:00.000Z", dur=5))
    soft_delete_event(conn, ev["id"])
    assert today_totals(conn) == {"tummy_time_min": 0}


def test_last_event_of_each_type_includes_tummy_time(conn):
    """`tummy_time` key surfaces when a tummy session exists."""
    create_event(conn, _evt("tummy_time", "tt1", f"{TODAY}T08:00:00.000Z", dur=5))
    out = last_event_of_each_type(conn)
    assert "tummy_time" in out
    assert out["tummy_time"]["occurred_at"] == f"{TODAY}T08:00:00.000Z"


def test_daily_totals_sums_tummy_minutes_per_day(conn):
    """daily_totals exposes `tummy_time_min` (sum of session durations)."""
    create_event(conn, _evt("tummy_time", "tt1", f"{TODAY}T08:00:00.000Z", dur=5))
    create_event(conn, _evt("tummy_time", "tt2", f"{TODAY}T11:00:00.000Z", dur=3))
    rows = daily_totals(conn, days=14)
    today_row = next(r for r in rows if r["day"] == TODAY)
    assert today_row["tummy_time"] == 2
    assert today_row["tummy_time_min"] == 8


def test_last_event_of_each_type_includes_vitd(conn):
    """`vitd` key surfaces when a vit D event exists."""
    create_event(conn, _evt("vitd", "v1", f"{TODAY}T09:00:00.000Z"))
    out = last_event_of_each_type(conn)
    assert "vitd" in out
    assert out["vitd"]["occurred_at"] == f"{TODAY}T09:00:00.000Z"


def test_daily_totals_row_includes_vitd(conn):
    create_event(conn, _evt("vitd", "v1", f"{TODAY}T09:00:00.000Z"))
    rows = daily_totals(conn, days=14)
    assert len(rows) == 1
    assert rows[0]["vitd"] == 1


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


def test_daily_totals_sums_formula_volume_ml_per_day(conn):
    """
    Each daily-totals row carries a `formula_ml` SUM so the reports
    table and the last-3-days mini-table can show per-day intake at a
    glance. Volume_ml NULLs are treated as 0.
    """
    create_event(
        conn, _evt("formula", "f1", f"{TODAY}T03:00:00.000Z", brand="Materna", volume_ml=120)
    )
    create_event(
        conn, _evt("formula", "f2", f"{TODAY}T06:00:00.000Z", brand="Materna", volume_ml=90)
    )
    create_event(
        conn, _evt("formula", "f3", f"{TODAY}T09:00:00.000Z", brand="Materna")
    )  # NULL volume
    rows = daily_totals(conn, days=14)
    assert len(rows) == 1
    assert rows[0]["formula_ml"] == 210


def test_daily_totals_formula_ml_zero_when_no_formula(conn):
    """Days with only breast/wee/poo events get `formula_ml = 0`."""
    create_event(conn, _evt("breast", "i1", f"{TODAY}T03:00:00.000Z"))
    rows = daily_totals(conn, days=14)
    assert rows[0]["formula_ml"] == 0


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
    # `breast` is also present (per-type key) alongside the combined `feed`.
    assert set(out) == {"breast", "feed", "wee"}
    assert out["feed"]["occurred_at"] == "2026-05-16T05:00:00.000Z"
    assert out["breast"]["occurred_at"] == "2026-05-16T05:00:00.000Z"
    assert "formula" not in out
    assert "poo" not in out


def test_last_event_of_each_type_ignores_deleted(conn):
    _, e, _ = create_event(conn, _evt("breast", "i1", "2026-05-16T03:00:00.000Z"))
    soft_delete_event(conn, e["id"])
    assert last_event_of_each_type(conn) == {}


def test_last_event_of_each_type_exposes_breast_and_formula_separately(conn):
    """
    Tile rows for breast and formula each show "last X" — they can't be
    driven from the combined `feed` key alone, otherwise whichever tile
    isn't the most-recent feed type shows "no recent" even when an event
    of its kind was logged earlier (production bug, May 2026).
    """
    create_event(conn, _evt("formula", "i1", "2026-05-16T02:00:00.000Z"))
    create_event(conn, _evt("breast", "i2", "2026-05-16T05:00:00.000Z"))
    out = last_event_of_each_type(conn)
    assert "breast" in out and "formula" in out
    assert out["breast"]["occurred_at"] == "2026-05-16T05:00:00.000Z"
    assert out["formula"]["occurred_at"] == "2026-05-16T02:00:00.000Z"
    # The combined `feed` key still reflects whichever was most recent.
    assert out["feed"]["occurred_at"] == "2026-05-16T05:00:00.000Z"


def test_last_event_of_each_type_omits_breast_or_formula_when_none_exist(conn):
    """Per-type keys are absent (not None) when no event of that type exists."""
    create_event(conn, _evt("breast", "i1", "2026-05-16T05:00:00.000Z"))
    out = last_event_of_each_type(conn)
    assert "breast" in out
    assert "formula" not in out
    assert out["feed"]["type"] == "breast"


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
