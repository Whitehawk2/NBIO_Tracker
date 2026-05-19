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
            {"occurred_at": "2026-05-16T08:00:00Z", "type": "breast"},
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
            {"occurred_at": "definitely-not-iso", "type": "breast"},
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
            "formula_ml": 0,
        }


# ---------- _timeline_marks --------------------------------------------------


class TestVitdOverdue:
    """`_vitd_overdue` decides whether the banner gets the .is-late class."""

    def test_not_late_before_18_when_not_given(self):
        assert pages._vitd_overdue({"vitd": 0}, local_hour=17) is False
        assert pages._vitd_overdue({"vitd": 0}, local_hour=9) is False

    def test_late_at_or_after_18_when_not_given(self):
        assert pages._vitd_overdue({"vitd": 0}, local_hour=18) is True
        assert pages._vitd_overdue({"vitd": 0}, local_hour=23) is True

    def test_never_late_once_given(self):
        """Logged today → calm regardless of hour."""
        assert pages._vitd_overdue({"vitd": 1}, local_hour=23) is False
        assert pages._vitd_overdue({"vitd": 3}, local_hour=20) is False

    def test_missing_vitd_key_treated_as_zero(self):
        """Defensive: missing key (older today_counts shape) is fine."""
        assert pages._vitd_overdue({}, local_hour=20) is True
        assert pages._vitd_overdue({}, local_hour=10) is False


class TestWeightHistoryContext:
    """`_weight_history_context` builds the reports section's data shape."""

    def test_empty_when_no_growth_rows(self, conn):
        ctx = pages._weight_history_context(conn)
        assert ctx == {"has_data": False}

    def test_single_measurement(self, conn):
        from nbio.models import GrowthCreate
        from nbio.repo import growth_create

        growth_create(
            conn,
            GrowthCreate(
                measured_at="2026-05-16",
                weight_g=3420,
                idempotency_key="idem-w-single",
                created_by_device="dev",
            ),
        )
        ctx = pages._weight_history_context(conn)
        assert ctx["has_data"] is True
        assert len(ctx["rows"]) == 1
        assert ctx["latest"]["weight_g"] == 3420
        assert ctx["latest"]["delta_g"] is None
        # One point in the chart.
        assert len(ctx["chart_points"]) == 1

    def test_delta_positive_negative_zero(self, conn):
        from nbio.models import GrowthCreate
        from nbio.repo import growth_create

        for d, w, idem in [
            ("2026-05-01", 3300, "idem-w-1"),
            ("2026-05-08", 3420, "idem-w-2"),  # +120
            ("2026-05-15", 3380, "idem-w-3"),  # -40
            ("2026-05-22", 3380, "idem-w-4"),  # 0
        ]:
            growth_create(
                conn,
                GrowthCreate(
                    measured_at=d,
                    weight_g=w,
                    idempotency_key=idem,
                    created_by_device="dev",
                ),
            )
        ctx = pages._weight_history_context(conn)
        # Rows are returned latest-first for the table.
        labels = [r["label"] for r in ctx["rows"]]
        assert labels == ["2026-05-22", "2026-05-15", "2026-05-08", "2026-05-01"]
        # Classes encode sign for CSS coloring.
        classes = {r["label"]: r["delta_class"] for r in ctx["rows"]}
        assert classes["2026-05-08"] == "delta-up"
        assert classes["2026-05-15"] == "delta-down"
        assert classes["2026-05-22"] == "delta-flat"
        assert classes["2026-05-01"] == ""  # no previous → empty class
        # Latest delta is the most recent diff.
        assert ctx["latest"]["delta_g"] == 0

    def test_chart_points_x_normalized_to_0_1000(self, conn):
        """First measurement → x=0; last → x=1000."""
        from nbio.models import GrowthCreate
        from nbio.repo import growth_create

        growth_create(
            conn,
            GrowthCreate(
                measured_at="2026-05-01",
                weight_g=3300,
                idempotency_key="idem-x-a",
                created_by_device="dev",
            ),
        )
        growth_create(
            conn,
            GrowthCreate(
                measured_at="2026-05-22",
                weight_g=3500,
                idempotency_key="idem-x-b",
                created_by_device="dev",
            ),
        )
        ctx = pages._weight_history_context(conn)
        pts = ctx["chart_points"]
        assert pts[0]["x"] == 0
        assert pts[-1]["x"] == 1000

    def test_chart_y_inverted_so_heavier_is_higher(self, conn):
        """SVG y axis grows downward — heavier weight = SMALLER y."""
        from nbio.models import GrowthCreate
        from nbio.repo import growth_create

        for d, w, idem in [
            ("2026-05-01", 3300, "idem-y-a"),
            ("2026-05-22", 3500, "idem-y-b"),
        ]:
            growth_create(
                conn,
                GrowthCreate(
                    measured_at=d,
                    weight_g=w,
                    idempotency_key=idem,
                    created_by_device="dev",
                ),
            )
        ctx = pages._weight_history_context(conn)
        pts = ctx["chart_points"]
        # The heavier point (3500g) must plot HIGHER (smaller y) than 3300g.
        heavier = next(p for p in pts if p["weight_g"] == 3500)
        lighter = next(p for p in pts if p["weight_g"] == 3300)
        assert heavier["y"] < lighter["y"]


class TestTummyDurationStr:
    """`_tummy_duration_str` formats tummy event durations for display."""

    def test_seconds_only_under_60(self):
        assert pages._tummy_duration_str({"feed_duration_sec": 42}) == "42s"

    def test_seconds_under_60_zero_is_empty(self):
        # Zero is meaningful — render as 0s, not "".
        assert pages._tummy_duration_str({"feed_duration_sec": 0}) == "0s"

    def test_seconds_exact_minute(self):
        assert pages._tummy_duration_str({"feed_duration_sec": 60}) == "1m"
        assert pages._tummy_duration_str({"feed_duration_sec": 300}) == "5m"

    def test_seconds_with_remainder(self):
        assert pages._tummy_duration_str({"feed_duration_sec": 95}) == "1m 35s"
        assert pages._tummy_duration_str({"feed_duration_sec": 600 + 15}) == "10m 15s"

    def test_falls_back_to_minutes_when_sec_missing(self):
        """Pre-006 legacy rows have only feed_duration_min — still render."""
        assert pages._tummy_duration_str({"feed_duration_min": 5}) == "5m"

    def test_sec_takes_precedence_over_min(self):
        """When both are set, sec wins (it's the more precise value)."""
        assert (
            pages._tummy_duration_str({"feed_duration_min": 5, "feed_duration_sec": 95}) == "1m 35s"
        )

    def test_both_null_returns_empty(self):
        assert pages._tummy_duration_str({}) == ""


class TestTummyOverdue:
    """`_tummy_overdue` decides whether the tummy banner gets `.is-late`."""

    def test_not_late_before_16_when_none_logged(self):
        assert pages._tummy_overdue({"tummy_time": 0}, local_hour=15) is False
        assert pages._tummy_overdue({"tummy_time": 0}, local_hour=9) is False

    def test_late_at_or_after_16_when_none_logged(self):
        assert pages._tummy_overdue({"tummy_time": 0}, local_hour=16) is True
        assert pages._tummy_overdue({"tummy_time": 0}, local_hour=23) is True

    def test_never_late_once_one_session(self):
        """Even one session today → calm regardless of hour."""
        assert pages._tummy_overdue({"tummy_time": 1}, local_hour=22) is False
        assert pages._tummy_overdue({"tummy_time": 3}, local_hour=20) is False

    def test_missing_tummy_key_treated_as_zero(self):
        assert pages._tummy_overdue({}, local_hour=20) is True
        assert pages._tummy_overdue({}, local_hour=8) is False


class TestAgeFromDob:
    """`_age_from_dob` renders compact baby ages for the header display."""

    @pytest.mark.parametrize(
        "dob,today,expected",
        [
            ("2026-05-16", date(2026, 5, 16), "0d"),
            ("2026-05-04", date(2026, 5, 16), "12d"),
            ("2026-05-09", date(2026, 5, 16), "7d"),  # boundary: <14d → days
            ("2026-04-25", date(2026, 5, 16), "3w"),  # 21d clean weeks
            ("2026-04-20", date(2026, 5, 16), "3w 5d"),  # 26d → 3w 5d
            ("2026-03-17", date(2026, 5, 16), "2m"),  # 60d → months
            ("2026-02-16", date(2026, 5, 16), "2m 4w"),  # 89d → 2m 29d → 2m + 4w
            ("2025-12-16", date(2026, 5, 16), "5m"),  # 151d → 5m + 1d → 5m
            ("2024-05-16", date(2026, 5, 16), "2y"),
            ("2023-11-16", date(2026, 5, 16), "2y 6m"),
        ],
    )
    def test_renders_expected_format(self, dob, today, expected):
        assert pages._age_from_dob(dob, today) == expected

    def test_none_dob_returns_none(self):
        assert pages._age_from_dob(None, date(2026, 5, 16)) is None

    def test_empty_string_returns_none(self):
        assert pages._age_from_dob("", date(2026, 5, 16)) is None

    def test_invalid_format_returns_none(self):
        assert pages._age_from_dob("not-a-date", date(2026, 5, 16)) is None
        assert pages._age_from_dob("20-04-2026", date(2026, 5, 16)) is None

    def test_future_dob_returns_none(self):
        """Defensive: a dob in the future shouldn't render as negative days."""
        assert pages._age_from_dob("2027-01-01", date(2026, 5, 16)) is None


class TestDayFormulaCc:
    def test_sums_formula_volume_for_day(self):
        events = [
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "formula", "formula_volume_ml": 120},
            {"occurred_at": "2026-05-16T08:00:00Z", "type": "formula", "formula_volume_ml": 90},
            {"occurred_at": "2026-05-15T22:00:00Z", "type": "formula", "formula_volume_ml": 200},
            {"occurred_at": "2026-05-16T10:00:00Z", "type": "breast"},
        ]
        # 120 + 90 = 210 for 2026-05-16; the 2026-05-15 event is excluded.
        assert pages._day_formula_cc(events, "2026-05-16") == 210
        # The breast event doesn't contribute.

    def test_zero_when_no_formula(self):
        events = [{"occurred_at": "2026-05-16T03:00:00Z", "type": "breast"}]
        assert pages._day_formula_cc(events, "2026-05-16") == 0

    def test_skips_formula_without_volume(self):
        events = [
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "formula", "formula_volume_ml": None},
            {"occurred_at": "2026-05-16T04:00:00Z", "type": "formula", "formula_volume_ml": 0},
            {"occurred_at": "2026-05-16T05:00:00Z", "type": "formula", "formula_volume_ml": 60},
        ]
        assert pages._day_formula_cc(events, "2026-05-16") == 60

    def test_skips_malformed_occurred_at(self):
        events = [
            {"occurred_at": "bad-iso", "type": "formula", "formula_volume_ml": 100},
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "formula", "formula_volume_ml": 60},
        ]
        assert pages._day_formula_cc(events, "2026-05-16") == 60


class TestTimelineMarks:
    def test_only_events_on_target_day(self):
        events = [
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "breast"},
            {"occurred_at": "2026-05-15T22:00:00Z", "type": "wee"},
        ]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        # breast → feed (timeline doesn't distinguish; both render as
        # `.mark-feed` which has fill: var(--feed)).
        assert marks[0]["type"] == "feed"
        # 03:00 UTC → 3*3600 seconds → x = 0.125
        assert abs(marks[0]["x"] - 0.125) < 0.001

    def test_skips_malformed_occurred_at(self):
        events = [
            {"occurred_at": "2026-05-16XX bad", "type": "breast"},
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "wee"},
        ]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        assert marks[0]["type"] == "wee"

    def test_poo_quality_renders_in_tooltip(self):
        """poo marks include their quality in the tooltip string."""
        events = [
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "poo", "poo_quality": 4},
        ]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        assert "type 4" in marks[0]["tooltip"]
        assert "03:00" in marks[0]["tooltip"]

    def test_unknown_type_is_skipped(self):
        """
        Defensive: if `e['type']` is something we don't recognise (shouldn't
        happen given EventType is constrained at the model layer, but
        guards against future schema drift), the mark is skipped rather
        than rendered with a missing class.
        """
        events = [
            {"occurred_at": "2026-05-16T03:00:00Z", "type": "unknown"},
            {"occurred_at": "2026-05-16T04:00:00Z", "type": "wee"},
        ]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        assert marks[0]["type"] == "wee"

    def test_vitd_event_maps_to_vitd_mark_with_tooltip(self):
        """Vit D events get their own mark class + a 'Vit D' tooltip."""
        events = [{"occurred_at": "2026-05-16T09:00:00Z", "type": "vitd"}]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        assert marks[0]["type"] == "vitd"
        assert "Vit D" in marks[0]["tooltip"]
        assert "09:00" in marks[0]["tooltip"]

    def test_tummy_time_event_maps_to_tummy_mark_with_tooltip(self):
        """Tummy time events get their own mark class + duration tooltip."""
        events = [
            {
                "occurred_at": "2026-05-16T08:00:00Z",
                "type": "tummy_time",
                "feed_duration_min": 5,
            }
        ]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        assert marks[0]["type"] == "tummy"
        # Legacy rows (no sec) still produce a minute-rendered tooltip.
        assert "Tummy 5m" in marks[0]["tooltip"]
        assert "08:00" in marks[0]["tooltip"]

    def test_tummy_time_tooltip_uses_seconds_when_present(self):
        """Sec-only timer rows render sub-minute precision in the tooltip."""
        events = [
            {
                "occurred_at": "2026-05-16T08:00:00Z",
                "type": "tummy_time",
                "feed_duration_sec": 95,  # 1m 35s
            }
        ]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        assert "Tummy 1m 35s" in marks[0]["tooltip"]

    def test_tummy_time_tooltip_seconds_only_for_under_a_minute(self):
        events = [
            {
                "occurred_at": "2026-05-16T08:00:00Z",
                "type": "tummy_time",
                "feed_duration_sec": 42,
            }
        ]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert "Tummy 42s" in marks[0]["tooltip"]

    def test_tummy_time_tooltip_without_duration(self):
        """Tummy event with no duration falls back to bare 'Tummy' label."""
        events = [{"occurred_at": "2026-05-16T08:00:00Z", "type": "tummy_time"}]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 1
        assert "Tummy" in marks[0]["tooltip"]
        assert "m" not in marks[0]["tooltip"].split("Tummy")[1]
        assert "s" not in marks[0]["tooltip"].split("Tummy")[1]

    def test_breast_and_formula_map_to_feed(self):
        events = [
            {"occurred_at": "2026-05-16T01:00:00Z", "type": "breast"},
            {"occurred_at": "2026-05-16T02:00:00Z", "type": "formula"},
        ]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert len(marks) == 2
        assert all(m["type"] == "feed" for m in marks)

    def test_local_date_bucketing(self, monkeypatch):
        """
        An event at 22:00 UTC on 2026-05-15 is 01:00 LOCAL on 2026-05-16
        in a UTC+3 zone. _timeline_marks must bucket by LOCAL date, not
        UTC prefix — otherwise the mark goes missing from the local-today
        timeline (the v1.1.0 'poos missing from today' bug).
        """
        # Simulate UTC+3 by setting the process TZ.
        import os
        import time

        monkeypatch.setenv("TZ", "Asia/Jerusalem")
        time.tzset()
        try:
            events = [{"occurred_at": "2026-05-15T22:00:00Z", "type": "poo"}]
            marks = pages._timeline_marks(events, "2026-05-16")
            assert len(marks) == 1, (
                "poo at 22:00 UTC = 01:00 local Jerusalem next day; must "
                "appear in the 2026-05-16 LOCAL timeline"
            )
            assert marks[0]["type"] == "poo"
        finally:
            os.environ["TZ"] = "UTC"
            time.tzset()

    def test_x_position_at_midnight(self):
        events = [{"occurred_at": "2026-05-16T00:00:00Z", "type": "breast"}]
        marks = pages._timeline_marks(events, "2026-05-16")
        assert marks[0]["x"] == 0.0

    def test_empty(self):
        assert pages._timeline_marks([], "2026-05-16") == []
