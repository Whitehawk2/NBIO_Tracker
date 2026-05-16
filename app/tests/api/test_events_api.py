"""HTTP layer for /api/events* — happy paths, dup statuses, 404s, validation."""


def _payload(**over):
    base = {
        "type": "feed",
        "occurred_at": "2026-05-16T03:00:00.000Z",
        "feed_side": "L",
        "feed_duration_min": 15,
        "idempotency_key": "idem-aaaaaaaa",
        "created_by_device": "device-test",
    }
    base.update(over)
    return base


def test_list_events_empty(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    assert r.json() == {"events": []}


def test_create_returns_created(client):
    r = client.post("/api/events", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "created"
    assert body["event"]["type"] == "feed"
    assert "duplicate_of" not in body


def test_create_already_exists_on_idem_replay(client):
    """Replaying the same payload returns already_exists, no new row."""
    client.post("/api/events", json=_payload(idempotency_key="idem-replay-1"))
    r = client.post("/api/events", json=_payload(idempotency_key="idem-replay-1"))
    assert r.json()["status"] == "already_exists"
    lst = client.get("/api/events").json()["events"]
    assert len(lst) == 1


def test_create_possible_duplicate(client):
    """Two events of the same type 60s apart → second flagged."""
    client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-dup-1", occurred_at="2026-05-16T03:00:00.000Z"),
    )
    r = client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-dup-2", occurred_at="2026-05-16T03:01:00.000Z"),
    )
    body = r.json()
    assert body["status"] == "created_possible_duplicate"
    assert "duplicate_of" in body


def test_create_skip_dup_check(client):
    """skip_dup_check=true suppresses the duplicate_of payload."""
    client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-skip-1", occurred_at="2026-05-16T03:00:00.000Z"),
    )
    r = client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-skip-2",
            occurred_at="2026-05-16T03:01:00.000Z",
            skip_dup_check=True,
        ),
    )
    body = r.json()
    assert body["status"] == "created"
    assert "duplicate_of" not in body


def test_create_validation_error(client):
    """Bad enum → 422."""
    bad = _payload(type="snack")
    r = client.post("/api/events", json=bad)
    assert r.status_code == 422


def test_list_events_since(client):
    client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-since1", occurred_at="2026-05-16T01:00:00.000Z"),
    )
    client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-since2", occurred_at="2026-05-16T05:00:00.000Z"),
    )
    r = client.get("/api/events?since=2026-05-16T04:00:00.000Z")
    assert len(r.json()["events"]) == 1


def test_list_events_invalid_limit_422(client):
    """Query bounds enforce ge=1, le=1000."""
    r = client.get("/api/events?limit=0")
    assert r.status_code == 422
    r = client.get("/api/events?limit=9999")
    assert r.status_code == 422


def test_patch_event(client):
    created = client.post("/api/events", json=_payload(idempotency_key="idem-patch-1")).json()
    event_id = created["event"]["id"]
    r = client.patch(f"/api/events/{event_id}", json={"feed_side": "R"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "updated"
    assert body["event"]["feed_side"] == "R"


def test_patch_missing_404(client):
    r = client.patch("/api/events/999", json={"feed_side": "R"})
    assert r.status_code == 404


def test_delete_event(client):
    created = client.post("/api/events", json=_payload(idempotency_key="idem-del-1")).json()
    event_id = created["event"]["id"]
    r = client.delete(f"/api/events/{event_id}")
    assert r.status_code == 200
    assert r.json() == {"status": "deleted", "id": event_id}
    # Default list no longer includes it
    assert client.get("/api/events").json()["events"] == []


def test_delete_missing_404(client):
    r = client.delete("/api/events/999")
    assert r.status_code == 404


def test_undelete(client):
    created = client.post("/api/events", json=_payload(idempotency_key="idem-undel-1")).json()
    event_id = created["event"]["id"]
    client.delete(f"/api/events/{event_id}")
    r = client.post(f"/api/events/{event_id}/undelete")
    assert r.status_code == 200
    assert r.json()["status"] == "undeleted"
    assert r.json()["event"]["deleted_at"] is None


def test_undelete_missing_404(client):
    r = client.post("/api/events/999/undelete")
    assert r.status_code == 404


def test_feeds_last_side(client):
    """Returns the side of the most recent non-deleted feed (null when none)."""
    assert client.get("/api/feeds/last-side").json() == {"last_side": None}
    client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-ls-1", occurred_at="2026-05-16T03:00:00.000Z"),
    )
    assert client.get("/api/feeds/last-side").json() == {"last_side": "L"}
