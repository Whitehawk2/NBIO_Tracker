"""
Tummy time events flow through the existing /api/events* endpoints (v1.1.1).

No new endpoints — the EventType literal addition + the migration 004
schema CHECK widening are enough to let `type="tummy_time"` POST / GET /
PATCH / DELETE / undelete through every existing path. These tests pin
the round-trip + a few negative cases so the wiring can't silently
regress.
"""

from __future__ import annotations


def _tummy_payload(**over):
    base = {
        "type": "tummy_time",
        "occurred_at": "2026-05-20T08:00:00.000Z",
        "feed_duration_min": 5,
        "idempotency_key": "idem-tummy-aa",
        "created_by_device": "device-test",
    }
    base.update(over)
    return base


def test_post_tummy_time_event_succeeds(client):
    r = client.post("/api/events", json=_tummy_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event"]["type"] == "tummy_time"
    assert body["event"]["feed_duration_min"] == 5


def test_get_event_by_id_round_trips_tummy(client):
    """GET /api/events/{id} returns the canonical row including duration."""
    created = client.post(
        "/api/events", json=_tummy_payload(idempotency_key="idem-tummy-rt")
    ).json()
    ev_id = created["event"]["id"]
    r = client.get(f"/api/events/{ev_id}")
    assert r.status_code == 200
    assert r.json()["event"]["type"] == "tummy_time"
    assert r.json()["event"]["feed_duration_min"] == 5


def test_tummy_event_with_notes(client):
    """Tummy events accept optional notes (e.g. 'after morning feed')."""
    r = client.post(
        "/api/events",
        json=_tummy_payload(idempotency_key="idem-tummy-notes", notes="post-feed"),
    )
    assert r.status_code == 200
    assert r.json()["event"]["notes"] == "post-feed"


def test_tummy_event_in_list(client):
    """GET /api/events lists the tummy row alongside the others."""
    client.post("/api/events", json=_tummy_payload(idempotency_key="idem-tummy-list"))
    r = client.get("/api/events")
    assert r.status_code == 200
    types = {ev["type"] for ev in r.json()["events"]}
    assert "tummy_time" in types


def test_tummy_event_soft_delete(client):
    """DELETE /api/events/{id} flags the tummy row as soft-deleted."""
    created = client.post(
        "/api/events", json=_tummy_payload(idempotency_key="idem-tummy-del")
    ).json()
    ev_id = created["event"]["id"]
    r = client.delete(f"/api/events/{ev_id}")
    assert r.status_code == 200
    body = client.get(f"/api/events/{ev_id}").json()
    assert body["event"]["deleted_at"] is not None


def test_tummy_event_idempotent_post(client):
    """Posting the same idempotency_key twice → second hits the dup path."""
    p = _tummy_payload(idempotency_key="idem-tummy-dup")
    r1 = client.post("/api/events", json=p)
    r2 = client.post("/api/events", json=p)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_exists"


def test_tummy_event_patch_duration(client):
    """PATCH a tummy event to change its duration."""
    created = client.post(
        "/api/events", json=_tummy_payload(idempotency_key="idem-tummy-patch")
    ).json()
    ev_id = created["event"]["id"]
    r = client.patch(f"/api/events/{ev_id}", json={"feed_duration_min": 10})
    assert r.status_code == 200
    assert r.json()["event"]["feed_duration_min"] == 10


def test_tummy_event_undelete(client):
    """POST /api/events/{id}/undelete clears the soft-delete flag."""
    created = client.post(
        "/api/events", json=_tummy_payload(idempotency_key="idem-tummy-undel")
    ).json()
    ev_id = created["event"]["id"]
    client.delete(f"/api/events/{ev_id}")
    r = client.post(f"/api/events/{ev_id}/undelete")
    assert r.status_code == 200
    assert r.json()["event"]["deleted_at"] is None
