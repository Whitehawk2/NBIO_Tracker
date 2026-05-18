"""
Vit D events flow through the existing /api/events* endpoints (#8.5).

No new endpoints — the EventType literal change in models.py + the
schema CHECK widening (migration 003) are enough to let type='vitd'
POST / PATCH / DELETE / undelete through every existing path. These
tests pin the round-trip + a few negative cases so the wiring can't
silently regress.
"""

from __future__ import annotations


def _vitd_payload(**over):
    base = {
        "type": "vitd",
        "occurred_at": "2026-05-20T09:00:00.000Z",
        "idempotency_key": "idem-vitd-aa",
        "created_by_device": "device-test",
    }
    base.update(over)
    return base


def test_post_vitd_event_succeeds(client):
    r = client.post("/api/events", json=_vitd_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event"]["type"] == "vitd"
    assert body["event"]["occurred_at"] == "2026-05-20T09:00:00.000Z"


def test_get_event_by_id_round_trips_vitd(client):
    """GET /api/events/{id} returns the canonical row including type='vitd'."""
    created = client.post("/api/events", json=_vitd_payload(idempotency_key="idem-vitd-rt")).json()
    ev_id = created["event"]["id"]
    r = client.get(f"/api/events/{ev_id}")
    assert r.status_code == 200
    assert r.json()["event"]["type"] == "vitd"


def test_vitd_event_with_notes(client):
    """Vit D events accept optional notes (e.g. 'gave with morning bottle')."""
    r = client.post(
        "/api/events",
        json=_vitd_payload(idempotency_key="idem-vitd-notes", notes="with bottle"),
    )
    assert r.status_code == 200
    assert r.json()["event"]["notes"] == "with bottle"


def test_unknown_event_type_rejected(client):
    """Anything outside the EventType literal must 422."""
    r = client.post(
        "/api/events",
        json={
            "type": "multivitamin",
            "occurred_at": "2026-05-20T09:00:00.000Z",
            "idempotency_key": "idem-bogus-type",
            "created_by_device": "device-test",
        },
    )
    assert r.status_code == 422


def test_vitd_event_in_list(client):
    """GET /api/events lists the vit D row alongside the others."""
    client.post("/api/events", json=_vitd_payload(idempotency_key="idem-vitd-list"))
    r = client.get("/api/events")
    assert r.status_code == 200
    types = {ev["type"] for ev in r.json()["events"]}
    assert "vitd" in types


def test_vitd_event_soft_delete(client):
    """DELETE /api/events/{id} flags the vit D row as soft-deleted."""
    created = client.post(
        "/api/events", json=_vitd_payload(idempotency_key="idem-vitd-del")
    ).json()
    ev_id = created["event"]["id"]
    r = client.delete(f"/api/events/{ev_id}")
    assert r.status_code == 200
    # The row is still fetchable (soft-delete) but flagged.
    body = client.get(f"/api/events/{ev_id}").json()
    assert body["event"]["deleted_at"] is not None


def test_vitd_event_idempotent_post(client):
    """Posting the same idempotency_key twice → second hits the dup path."""
    p = _vitd_payload(idempotency_key="idem-vitd-dup")
    r1 = client.post("/api/events", json=p)
    r2 = client.post("/api/events", json=p)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_exists"
