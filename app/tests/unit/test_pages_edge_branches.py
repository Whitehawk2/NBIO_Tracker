"""
Per-branch coverage AND behavioural assertions for the defensive branches
in routes/pages.py.

The previous incarnation (PR #16) hit each branch but asserted only
`status_code == 200` — coverage theatre per the review (issue #21,
critical gap 1). This version asserts on the *rendered* fallback so a
regression that swallowed the exception silently into an empty page
would still fail.
"""

from datetime import UTC

from nbio.models import EventCreate
from nbio.repo import create_event


def _payload(idem, t="breast", occurred_at="2026-05-16T03:00:00.000Z"):
    return EventCreate(
        type=t,
        occurred_at=occurred_at,
        idempotency_key=idem,
        created_by_device="device-test",
    )


def test_reports_handles_malformed_day_in_totals(client, monkeypatch):
    """
    If daily_totals returns a row with an unparseable `day`, the route
    falls through to `row.get("day", "")` for the label without crashing.
    The reports.html template renders `{{ row.label or row.day }}` → the
    raw bad value should appear in a totals-table cell.
    """
    from nbio.routes import pages

    def fake_totals(*a, **kw):
        return [{"day": "not-a-date", "feed": 7, "wee": 5, "poo": 3}]

    monkeypatch.setattr(pages.repo, "daily_totals", fake_totals)
    r = client.get("/reports")
    assert r.status_code == 200
    # Markup that confirms the totals table actually rendered
    assert 'id="totals-body"' in r.text
    # The raw bad day string appears in a cell (label fell back to row["day"])
    assert "<td>not-a-date</td>" in r.text
    # And the data columns are still populated
    assert "<td>7</td>" in r.text


def test_reports_handles_missing_day_key(client, monkeypatch):
    """
    If the row doesn't even have a `day` key, get('day', '') = '' applies.
    Template renders `{{ row.label or row.day }}` → empty cell.
    """
    from nbio.routes import pages

    def fake_totals(*a, **kw):
        return [{"feed": 2, "wee": 1, "poo": 0}]  # no 'day' key

    monkeypatch.setattr(pages.repo, "daily_totals", fake_totals)
    r = client.get("/reports")
    assert r.status_code == 200
    tbody_start = r.text.find('id="totals-body"')
    tbody_end = r.text.find("</tbody>", tbody_start)
    tbody = r.text[tbody_start:tbody_end]
    # Empty label cell present, but the count columns still render
    assert "<td></td>" in tbody
    assert "<td>2</td>" in tbody
    assert "<td>1</td>" in tbody


def test_reports_skips_malformed_occurred_at_in_heatmap(client, conn):
    """
    The heatmap accumulator's `except ValueError` swallows bad
    occurred_at. Insert one good + one malformed event; assert the page
    renders, the heatmap grid is present, and the good event's hour
    bucket is reflected via at least one non-baseline opacity in the
    heatmap.
    """
    # Direct-insert: bypass the model validator that would reject malformed dates
    conn.execute(
        """
        INSERT INTO events (
            baby_id, type, occurred_at, idempotency_key, created_by_device
        ) VALUES (1, 'breast', 'completely-not-iso', 'idem-malformed1', 'device-test')
        """
    )
    # And one valid event today (uses real wall-clock for "today" — fine because
    # we only assert the heatmap renders and contains *some* non-baseline cell)
    from datetime import datetime

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    conn.execute(
        """
        INSERT INTO events (
            baby_id, type, occurred_at, idempotency_key, created_by_device
        ) VALUES (1, 'breast', ?, 'idem-validone', 'device-test')
        """,
        (f"{today}T03:00:00.000Z",),
    )
    r = client.get("/reports")
    assert r.status_code == 200
    assert 'class="heatmap-grid"' in r.text
    # Heatmap renders cells with opacity. The baseline for empty cells is 0.06.
    # The good event drove at least one cell to a higher opacity.
    # Look for any opacity value > 0.06.
    import re

    opacities = [float(m.group(1)) for m in re.finditer(r"opacity:\s*([\d.]+);", r.text)]
    assert opacities, "no heatmap cells rendered"
    assert any(op > 0.06 for op in opacities), (
        "the valid event should have driven one heatmap cell above baseline opacity"
    )


def test_reports_event_outside_7day_window_does_not_blow_up(client, conn):
    """
    A 2020-era event shouldn't contribute to the heatmap (delta>=7 branch
    in routes/pages.py). Assert: page still renders, heatmap is present,
    and no cell is driven above baseline by the ancient event.
    """
    create_event(conn, _payload("idem-ancient-1", occurred_at="2020-01-01T03:00:00.000Z"))
    r = client.get("/reports")
    assert r.status_code == 200
    assert 'class="heatmap-grid"' in r.text

    import re

    opacities = {float(m.group(1)) for m in re.finditer(r"opacity:\s*([\d.]+);", r.text)}
    # Only the baseline opacity (0.06) should be present — the ancient event
    # was outside the 7-day window so didn't bump any cell.
    assert opacities == {0.06}, (
        f"event outside the 7-day window leaked into the heatmap: opacities={opacities}"
    )
