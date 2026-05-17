"""
`nbio.tz` — helpers for translating Python's tzdata into SQLite-friendly
date arithmetic. The bug they fix (issue #28 #1): late-evening local-time
entries appeared one day earlier in the "Last 3 days" overview because
`repo.daily_totals` / `repo.today_counts` bucketed by UTC date while the
event list correctly bucketed by local date.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from nbio.tz import local_offset_modifier, local_today_str

# ---------- local_offset_modifier ------------------------------------------


def test_utc_returns_zero_minutes():
    assert local_offset_modifier("UTC") == "+0 minutes"


def test_bst_in_may_is_plus_60_minutes():
    """Europe/London on 2026-05-16 is in BST (UTC+1)."""
    moment = datetime(2026, 5, 16, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert local_offset_modifier("Europe/London", now=moment) == "+60 minutes"


def test_gmt_in_january_is_plus_zero():
    """Europe/London in January is GMT (UTC+0)."""
    moment = datetime(2026, 1, 16, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert local_offset_modifier("Europe/London", now=moment) == "+0 minutes"


def test_eastern_us_in_winter_is_minus_300_minutes():
    """America/New_York in January is EST (UTC-5)."""
    moment = datetime(2026, 1, 16, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert local_offset_modifier("America/New_York", now=moment) == "-300 minutes"


def test_eastern_us_in_summer_is_minus_240_minutes():
    """America/New_York in July is EDT (UTC-4)."""
    moment = datetime(2026, 7, 16, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert local_offset_modifier("America/New_York", now=moment) == "-240 minutes"


def test_naive_datetime_is_interpreted_as_utc():
    """A naive datetime should be treated as UTC (matches Python's default)."""
    naive = datetime(2026, 5, 16, 12, 0)  # no tzinfo
    assert local_offset_modifier("Europe/London", now=naive) == "+60 minutes"


def test_uses_current_time_when_now_is_omitted():
    """Sanity: calling without `now` returns a non-empty modifier string."""
    out = local_offset_modifier("UTC")
    assert out.endswith(" minutes")


# ---------- local_today_str ------------------------------------------------


def test_local_today_str_utc():
    moment = datetime(2026, 5, 16, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert local_today_str("UTC", now=moment) == "2026-05-16"


def test_local_today_str_bst_crosses_midnight_forward():
    """
    At 2026-05-16 23:30 UTC, Europe/London (BST) is 2026-05-17 00:30.
    Local-today should be the next day.
    """
    moment = datetime(2026, 5, 16, 23, 30, tzinfo=ZoneInfo("UTC"))
    assert local_today_str("Europe/London", now=moment) == "2026-05-17"


def test_local_today_str_eastern_us_crosses_midnight_backward():
    """
    At 2026-05-16 03:00 UTC, America/New_York (EDT, -4) is 2026-05-15 23:00.
    Local-today should be the previous day.
    """
    moment = datetime(2026, 5, 16, 3, 0, tzinfo=ZoneInfo("UTC"))
    assert local_today_str("America/New_York", now=moment) == "2026-05-15"


def test_local_today_str_naive_treated_as_utc():
    naive = datetime(2026, 5, 16, 23, 30)
    assert local_today_str("Europe/London", now=naive) == "2026-05-17"
