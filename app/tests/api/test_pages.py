"""HTML page renders: GET / and GET /reports → 200 + key markup."""

from datetime import UTC


def _payload(**over):
    base = {
        "type": "feed",
        "occurred_at": "2026-05-16T03:00:00.000Z",
        "feed_side": "L",
        "feed_duration_min": 15,
        "idempotency_key": "idem-pages-aa",
        "created_by_device": "device-test",
    }
    base.update(over)
    return base


def test_index_renders_empty(client):
    """Page renders even with no events seeded."""
    r = client.get("/")
    assert r.status_code == 200
    # Look for any plausible marker — title, baby name, etc.
    body = r.text
    assert "Test Baby" in body or "NBIO" in body or "feed" in body.lower()


def test_index_renders_with_events(client):
    client.post("/api/events", json=_payload(idempotency_key="idem-pages-1"))
    client.post(
        "/api/events",
        json=_payload(
            type="poo",
            idempotency_key="idem-pages-2",
            occurred_at="2026-05-16T04:00:00.000Z",
            poo_quality=4,
        ),
    )
    r = client.get("/")
    assert r.status_code == 200


def test_reports_renders_empty(client):
    r = client.get("/reports")
    assert r.status_code == 200


def test_reports_renders_with_events(client):
    """Exercise the daily_totals / timeline / heatmap branches."""
    from datetime import datetime

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for i in range(5):
        client.post(
            "/api/events",
            json=_payload(
                idempotency_key=f"idem-rpts-{i:04d}",
                occurred_at=f"{today}T{i:02d}:00:00.000Z",
                feed_duration_min=10 + i,
            ),
        )
    r = client.get("/reports")
    assert r.status_code == 200
