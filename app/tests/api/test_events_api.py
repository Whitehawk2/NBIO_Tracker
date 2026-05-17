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
    first = client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-dup-1", occurred_at="2026-05-16T03:00:00.000Z"),
    ).json()
    r = client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-dup-2", occurred_at="2026-05-16T03:01:00.000Z"),
    )
    body = r.json()
    assert body["status"] == "created_possible_duplicate"
    # The duplicate_of payload must be a full dict with the documented shape —
    # not just a presence-of-key check (issue #21 worth-fixing).
    dup = body["duplicate_of"]
    assert isinstance(dup, dict)
    assert dup["id"] == first["event"]["id"]
    assert dup["occurred_at"] == "2026-05-16T03:00:00.000Z"
    assert dup["type"] == "feed"
    assert dup["created_by_device"] == "device-test"
    # 60s difference between the two timestamps
    assert abs(dup["delta_seconds"]) == 60


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


def test_list_events_filters_deleted_at_the_api_layer(client):
    """
    Belt-and-braces: repo tests prove the SQL filter; this one proves
    the route doesn't accidentally start passing include_deleted=True
    (issue #21 worth-fixing).
    """
    created = client.post("/api/events", json=_payload(idempotency_key="idem-del-flt-1")).json()
    event_id = created["event"]["id"]
    # Sanity: present before delete
    assert any(e["id"] == event_id for e in client.get("/api/events").json()["events"])
    # Soft-delete it
    client.delete(f"/api/events/{event_id}")
    # And it's gone from the default GET
    listed = client.get("/api/events").json()["events"]
    assert not any(e["id"] == event_id for e in listed), "deleted event leaked into GET /api/events"


def test_patch_updates_at_is_strictly_later_than_created_at(client, freezer):
    """
    Invariant: after PATCH, updated_at > created_at. Without freezer, the
    inequality could trivially hold via microsecond drift; this version
    pins two distinct moments so it must actually move forward
    (issue #21 worth-fixing — no invariant assertions previously).
    """
    freezer.move_to("2026-05-16T03:00:00Z")
    created = client.post("/api/events", json=_payload(idempotency_key="idem-inv-1")).json()
    event_id = created["event"]["id"]
    initial_created_at = created["event"]["created_at"]
    initial_updated_at = created["event"]["updated_at"]
    # Sanity: created_at == updated_at on initial insert
    assert initial_created_at == initial_updated_at

    freezer.move_to("2026-05-16T03:30:00Z")
    patched = client.patch(f"/api/events/{event_id}", json={"notes": "late"}).json()
    # Strict ordering: updated_at > created_at after a write 30 min later
    assert patched["event"]["updated_at"] > patched["event"]["created_at"]
    # And monotonic vs the previous state
    assert patched["event"]["updated_at"] > initial_updated_at


def test_delete_then_undelete_round_trip(client, freezer):
    """
    API contract: delete + undelete leaves the row visible again, and
    monotonic timestamps hold across the cycle. The deeper "deleted_at >=
    created_at" invariant is asserted at the repo layer (where the row
    is directly inspectable). Here we verify the round-trip surfaces
    expected updated_at progression.
    """
    freezer.move_to("2026-05-16T03:00:00Z")
    created = client.post("/api/events", json=_payload(idempotency_key="idem-inv-del")).json()
    event_id = created["event"]["id"]
    first_updated = created["event"]["updated_at"]

    freezer.move_to("2026-05-16T03:15:00Z")
    client.delete(f"/api/events/{event_id}")

    freezer.move_to("2026-05-16T03:20:00Z")
    restored = client.post(f"/api/events/{event_id}/undelete").json()
    assert restored["event"]["deleted_at"] is None
    # Monotonic: each subsequent write bumps updated_at
    assert restored["event"]["updated_at"] > first_updated


# ---------------------------------------------------------------------------
# GET /api/events/{id} — required so the edit modal can fetch the full row
# instead of relying on whatever the server happened to render into the
# `.event-row`'s DOM. The legacy client-side hydration in app.js hard-codes
# `notes: null` for every server-rendered row, which is why notes appeared
# to vanish after a page reload (issue #28 finding #4).
# ---------------------------------------------------------------------------


def test_get_event_by_id_returns_full_row(client):
    created = client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-getbyid-1", notes="midnight feed, both sides"),
    ).json()
    event_id = created["event"]["id"]

    r = client.get(f"/api/events/{event_id}")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"event"}
    event = body["event"]
    # Every contract field should surface — this is what the modal will read
    expected_keys = {
        "id",
        "baby_id",
        "type",
        "occurred_at",
        "feed_side",
        "feed_duration_min",
        "poo_quality",
        "notes",
        "idempotency_key",
        "created_by_device",
        "created_at",
        "updated_at",
        "deleted_at",
        "actor_color",
        "actor_name",
    }
    assert expected_keys <= set(event), f"missing keys: {expected_keys - set(event)}"
    assert event["id"] == event_id
    assert event["notes"] == "midnight feed, both sides"
    assert event["type"] == "feed"
    assert event["feed_side"] == "L"


def test_get_event_by_id_404_for_missing(client):
    r = client.get("/api/events/999999")
    assert r.status_code == 404


def test_get_event_with_notes_round_trips_via_modal_path(client):
    """
    Belt-and-braces for #28-#4: POST with notes, GET by id, the notes
    value is exactly what we wrote. This is the exact path the modal
    will follow on row-click.
    """
    notes = "ate well, burped, no fuss"
    created = client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-roundtrip-notes", notes=notes),
    ).json()
    event_id = created["event"]["id"]
    fetched = client.get(f"/api/events/{event_id}").json()["event"]
    assert fetched["notes"] == notes


def test_get_event_by_id_returns_deleted_row(client):
    """
    Soft-deleted rows are still fetchable by id so the modal can show an
    'undelete' affordance and the user can recover an accidental delete.
    """
    created = client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-deleted-getbyid", notes="oops"),
    ).json()
    event_id = created["event"]["id"]
    client.delete(f"/api/events/{event_id}")

    r = client.get(f"/api/events/{event_id}")
    assert r.status_code == 200
    event = r.json()["event"]
    assert event["id"] == event_id
    assert event["notes"] == "oops"
    assert event["deleted_at"] is not None


def test_feeds_last_side(client):
    """Returns the side of the most recent non-deleted feed (null when none)."""
    assert client.get("/api/feeds/last-side").json() == {"last_side": None}
    client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-ls-1", occurred_at="2026-05-16T03:00:00.000Z"),
    )
    assert client.get("/api/feeds/last-side").json() == {"last_side": "L"}
