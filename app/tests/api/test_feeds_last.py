"""
GET /api/feeds/last — returns the most recent feed event (breast OR
formula) with enough detail for the modal to pre-fill smart defaults.

Also tests the legacy /api/feeds/last-side alias still works (returns
the side for breast feeds, null for formula or no feeds).

Issue #28 finding #5, stage 4.
"""

from __future__ import annotations


def _payload(**over):
    base = {
        "type": "breast",
        "occurred_at": "2026-05-16T03:00:00.000Z",
        "feed_side": "L",
        "feed_duration_min": 15,
        "idempotency_key": "idem-feedlast-aa",
        "created_by_device": "device-test",
    }
    base.update(over)
    return base


def test_feeds_last_empty_db_returns_null(client):
    """No feeds yet → {"last": null}."""
    r = client.get("/api/feeds/last")
    assert r.status_code == 200
    assert r.json() == {"last": None}


def test_feeds_last_returns_breast_shape(client):
    """After one breast feed, the payload exposes feed_side + duration."""
    client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-fl-breast-1"),
    )
    body = client.get("/api/feeds/last").json()
    assert body["last"] is not None
    last = body["last"]
    assert last["type"] == "breast"
    assert last["feed_side"] == "L"
    assert last["feed_duration_min"] == 15
    # Formula fields explicitly null on a breast row
    assert last["formula_brand"] is None
    assert last["formula_volume_ml"] is None


def test_feeds_last_returns_formula_shape(client):
    """After one formula feed, the payload exposes brand + volume."""
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-fl-formula-1",
            type="formula",
            feed_side=None,
            feed_duration_min=None,
            formula_brand="Materna",
            formula_volume_ml=120,
        ),
    )
    body = client.get("/api/feeds/last").json()
    assert body["last"]["type"] == "formula"
    assert body["last"]["formula_brand"] == "Materna"
    assert body["last"]["formula_volume_ml"] == 120
    assert body["last"]["feed_side"] is None
    assert body["last"]["feed_duration_min"] is None


def test_feeds_last_picks_most_recent_across_types(client):
    """Breast at T, formula at T+1h → returns formula."""
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-fl-mixed-breast",
            occurred_at="2026-05-16T03:00:00.000Z",
            feed_side="L",
        ),
    )
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-fl-mixed-formula",
            type="formula",
            occurred_at="2026-05-16T04:00:00.000Z",
            feed_side=None,
            feed_duration_min=None,
            formula_brand="Nutrilon",
            formula_volume_ml=60,
        ),
    )
    last = client.get("/api/feeds/last").json()["last"]
    assert last["type"] == "formula"
    assert last["formula_brand"] == "Nutrilon"


def test_feeds_last_ignores_deleted(client):
    """A soft-deleted feed is skipped when picking the most recent."""
    r = client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-fl-deleted",
            occurred_at="2026-05-16T05:00:00.000Z",
            type="formula",
            feed_side=None,
            feed_duration_min=None,
            formula_brand="Materna",
            formula_volume_ml=90,
        ),
    )
    formula_id = r.json()["event"]["id"]
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-fl-breast-older",
            occurred_at="2026-05-16T04:00:00.000Z",
            feed_side="R",
        ),
    )
    # Delete the formula → last should fall back to the breast row
    client.delete(f"/api/events/{formula_id}")
    last = client.get("/api/feeds/last").json()["last"]
    assert last["type"] == "breast"
    assert last["feed_side"] == "R"


def test_feeds_last_ignores_non_feed_types(client):
    """A more-recent wee/poo doesn't displace the last breast feed."""
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-fl-only-breast",
            occurred_at="2026-05-16T03:00:00.000Z",
        ),
    )
    client.post(
        "/api/events",
        json={
            "type": "wee",
            "occurred_at": "2026-05-16T05:00:00.000Z",
            "idempotency_key": "idem-fl-wee",
            "created_by_device": "device-test",
        },
    )
    last = client.get("/api/feeds/last").json()["last"]
    assert last["type"] == "breast"


# ---------------------------------------------------------------------------
# Legacy /api/feeds/last-side alias — preserved for clients that didn't
# update yet. Returns the side of the most recent BREAST feed; null for
# formula or no feeds.
# ---------------------------------------------------------------------------


def test_feeds_last_side_legacy_still_works(client):
    assert client.get("/api/feeds/last-side").json() == {"last_side": None}
    client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-fls-breast", feed_side="R"),
    )
    assert client.get("/api/feeds/last-side").json() == {"last_side": "R"}


def test_feeds_last_side_returns_null_for_formula_last(client):
    """If the most recent feed is formula, last-side returns null."""
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-fls-formula",
            type="formula",
            feed_side=None,
            feed_duration_min=None,
            formula_brand="Materna",
            formula_volume_ml=120,
        ),
    )
    assert client.get("/api/feeds/last-side").json() == {"last_side": None}


def test_feeds_last_side_returns_last_breast_side_even_with_newer_formula(client):
    """
    Legacy contract: last-side is the side of the most recent BREAST
    feed. A newer formula feed does NOT clear the side — clients that
    use the legacy endpoint just want to remember which boob was last.
    """
    # Breast first
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-fls-breast-old",
            feed_side="L",
            occurred_at="2026-05-16T03:00:00.000Z",
        ),
    )
    # Formula later — shouldn't affect last-side
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-fls-formula-newer",
            type="formula",
            occurred_at="2026-05-16T04:00:00.000Z",
            feed_side=None,
            feed_duration_min=None,
            formula_brand="Nutrilon",
            formula_volume_ml=60,
        ),
    )
    assert client.get("/api/feeds/last-side").json() == {"last_side": "L"}
