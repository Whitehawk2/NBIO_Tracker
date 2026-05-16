"""
Cover the last leftover branches in routes/pages.py:
- The `except (KeyError, ValueError)` fallback in `reports` when a totals
  row's `day` field is malformed.
- The `except ValueError` skip in the heatmap accumulator.
- The "event outside the 7-day window" path (branch 199→193).
"""

from nbio.models import EventCreate
from nbio.repo import create_event


def _payload(idem, t="feed", occurred_at="2026-05-16T03:00:00.000Z"):
    return EventCreate(
        type=t,
        occurred_at=occurred_at,
        idempotency_key=idem,
        created_by_device="device-test",
    )


def test_reports_handles_malformed_day_in_totals(client, monkeypatch):
    """If `daily_totals` returns a row with an unparseable `day`, the route
    falls back to `row.get('day', '')` for the label without crashing."""
    from nbio.routes import pages

    def fake_totals(*a, **kw):
        return [{"day": "not-a-date", "feed": 0, "wee": 0, "poo": 0}]

    monkeypatch.setattr(pages.repo, "daily_totals", fake_totals)
    r = client.get("/reports")
    assert r.status_code == 200


def test_reports_handles_malformed_day_with_missing_key(client, monkeypatch):
    """If the row doesn't even have a `day` key, the get('day', '') default applies."""
    from nbio.routes import pages

    def fake_totals(*a, **kw):
        return [{"feed": 1, "wee": 0, "poo": 0}]  # no 'day' key

    monkeypatch.setattr(pages.repo, "daily_totals", fake_totals)
    r = client.get("/reports")
    assert r.status_code == 200


def test_reports_skips_malformed_occurred_at_in_heatmap(client, conn):
    """The heatmap accumulator's `except ValueError` swallows bad occurred_at."""
    # Direct-insert a row whose occurred_at violates fromisoformat
    conn.execute(
        """
        INSERT INTO events (
            baby_id, type, occurred_at, idempotency_key, created_by_device
        ) VALUES (1, 'feed', 'completely-not-iso', 'idem-malformed', 'device-test')
        """
    )
    r = client.get("/reports")
    assert r.status_code == 200


def test_reports_event_outside_7day_window(client, conn):
    """A 2020-era event shouldn't contribute to the heatmap (delta>=7 branch)."""
    create_event(conn, _payload("idem-ancient-1", occurred_at="2020-01-01T03:00:00.000Z"))
    r = client.get("/reports")
    assert r.status_code == 200
