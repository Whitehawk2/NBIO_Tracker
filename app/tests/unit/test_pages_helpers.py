"""
Per-branch coverage for the Jinja helpers and aggregation functions in
routes/pages.py. These are pure-ish and easy to drive without a request.
"""

from datetime import date

import pytest

from nbio.routes import pages

# ---------- _relative ---------------------------------------------------------


class TestRelative:
    @pytest.mark.parametrize(
        "occurred,expected",
        [
            ("not-an-iso-date", ""),
            ("", ""),
        ],
    )
    def test_invalid_returns_empty(self, occurred, expected):
        assert pages._relative(occurred) == expected

    def test_just_now(self, freezer):
        freezer.move_to("2026-05-16T03:00:00Z")
        assert pages._relative("2026-05-16T02:59:30Z") == "just now"

    def test_minutes(self, freezer):
        freezer.move_to("2026-05-16T03:00:00Z")
        assert pages._relative("2026-05-16T02:45:00Z") == "15 min ago"

    def test_hours_round_only(self, freezer):
        freezer.move_to("2026-05-16T05:00:00Z")
        assert pages._relative("2026-05-16T03:00:00Z") == "2h ago"

    def test_hours_and_minutes(self, freezer):
        freezer.move_to("2026-05-16T05:14:00Z")
        # 2h 14m diff
        assert pages._relative("2026-05-16T03:00:00Z") == "2h 14m ago"

    def test_days(self, freezer):
        freezer.move_to("2026-05-18T03:00:00Z")
        assert pages._relative("2026-05-16T03:00:00Z") == "2d ago"


# ---------- _local_hhmm -------------------------------------------------------


class TestLocalHhmm:
    def test_happy(self):
        # UTC env (set in conftest) → no offset
        assert pages._local_hhmm("2026-05-16T03:07:00Z") == "03:07"

    def test_invalid_returns_empty(self):
        assert pages._local_hhmm("nope") == ""


# ---------- _day_label --------------------------------------------------------


class TestDayLabel:
    def test_today(self):
        d = date(2026, 5, 16)
        assert pages._day_label(d, d) == "Today"

    def test_yesterday(self):
        today = date(2026, 5, 16)
        assert pages._day_label(date(2026, 5, 15), today) == "Yesterday"

    def test_weekday_format(self):
        # Mon 11 May
        today = date(2026, 5, 16)  # Saturday
        out = pages._day_label(date(2026, 5, 11), today)
        assert out == "Mon 11 May"


# ---------- _group_events_by_local_day ---------------------------------------


class TestGroupByLocalDay:
    def test_groups_by_day(self, freezer):
        freezer.move_to("2026-05-16T12:00:00Z")
        events = [
            {"occurred_at": "2026-05-16T08:00:00Z", "type": "feed"},
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "wee"},
            {"occurred_at": "2026-05-15T22:00:00Z", "type": "poo"},
        ]
        groups = pages._group_events_by_local_day(events)
        assert len(groups) == 2
        # Newest-day first
        assert groups[0]["day"] == "2026-05-16"
        assert groups[0]["label"] == "Today"
        assert groups[1]["day"] == "2026-05-15"
        assert groups[1]["label"] == "Yesterday"
        assert len(groups[0]["events"]) == 2

    def test_skips_malformed_occurred_at(self, freezer):
        freezer.move_to("2026-05-16T12:00:00Z")
        events = [
            {"occurred_at": "definitely-not-iso", "type": "feed"},
            {"occurred_at": "2026-05-16T08:00:00Z", "type": "wee"},
        ]
        groups = pages._group_events_by_local_day(events)
        # Only the valid event made it
        assert sum(len(g["events"]) for g in groups) == 1

    def test_empty_input(self):
        assert pages._group_events_by_local_day([]) == []


# ---------- _last_days_rows --------------------------------------------------


class TestLastDaysRows:
    def test_pads_missing_days_with_zeros(self, freezer):
        freezer.move_to("2026-05-16T12:00:00Z")
        # Only one row supplied
        totals = [{"day": "2026-05-16", "feed": 3, "wee": 2, "poo": 1}]
        rows = pages._last_days_rows(totals, n=3)
        assert [r["day"] for r in rows] == ["2026-05-16", "2026-05-15", "2026-05-14"]
        # Day-with-data preserves counts; others zero-pad
        assert rows[0]["feed"] == 3
        assert rows[1] == {
            "day": "2026-05-15",
            "label": "Yesterday",
            "feed": 0,
            "wee": 0,
            "poo": 0,
        }


# ---------- _timeline_marks --------------------------------------------------


class TestTimelineMarks:
    def test_only_events_on_target_day(self):
        events = [
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "feed"},
            {"occurred_at": "2026-05-15T22:00:00Z", "type": "wee"},
        ]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        assert marks[0]["type"] == "feed"
        # 03:00 UTC → 3*3600 seconds → x = 0.125
        assert abs(marks[0]["x"] - 0.125) < 0.001

    def test_skips_malformed_occurred_at(self):
        events = [
            {"occurred_at": "2026-05-16XX bad", "type": "feed"},
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "wee"},
        ]
        # Both startswith "2026-05-16" so the date prefix check passes.
        # The fromisoformat will then raise on the bad one — the function
        # continues without it.
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        assert marks[0]["type"] == "wee"

    def test_x_position_at_midnight(self):
        events = [{"occurred_at": "2026-05-16T00:00:00Z", "type": "feed"}]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert marks[0]["x"] == 0.0

    def test_empty(self):
        assert pages._timeline_marks([], "2026-05-16") == []
