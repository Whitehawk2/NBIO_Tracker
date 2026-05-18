"""
GET / PATCH `/api/settings` and PATCH `/api/babies` (#6).

Each PATCH route also publishes an SSE event (`settings.updated` /
`baby.updated`) so two-parent setups stay in sync. The SSE assertions
subscribe a fresh queue to `nbio.sse.broker` and inspect the next
message — the broker is a process-level singleton (`CLAUDE.md` sharp
edge: mutate, don't rebind).
"""

from __future__ import annotations

from nbio.sse import broker


def test_get_settings_returns_seeded_row(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["settings"]["id"] == 1
    assert body["settings"]["tz"] is None
    assert body["settings"]["notes_md"] is None


def test_patch_settings_persists_and_returns_updated_row(client):
    r = client.patch("/api/settings", json={"tz": "Europe/London"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["settings"]["tz"] == "Europe/London"
    # Persists across requests.
    assert client.get("/api/settings").json()["settings"]["tz"] == "Europe/London"


def test_patch_settings_partial_keeps_other_fields(client):
    client.patch("/api/settings", json={"notes_md": "keep me"})
    client.patch("/api/settings", json={"tz": "Asia/Jerusalem"})
    body = client.get("/api/settings").json()["settings"]
    assert body["tz"] == "Asia/Jerusalem"
    assert body["notes_md"] == "keep me"


def test_patch_settings_rejects_invalid_tz(client):
    r = client.patch("/api/settings", json={"tz": "Europe/Atlantis"})
    assert r.status_code == 422


def test_patch_settings_rejects_extra_fields(client):
    r = client.patch("/api/settings", json={"tz": "UTC", "rogue": "x"})
    assert r.status_code == 422


def test_patch_settings_emits_sse(client):
    q = broker.subscribe()
    try:
        r = client.patch("/api/settings", json={"tz": "UTC"})
        assert r.status_code == 200
        assert not q.empty(), "patch /api/settings must publish to the SSE broker"
        event_name, event_id, payload = q.get_nowait()
        assert event_name == "settings.updated"
        assert payload["tz"] == "UTC"
        assert payload["id"] == 1
    finally:
        broker.unsubscribe(q)


def test_patch_baby_persists(client):
    r = client.patch("/api/babies", json={"name": "Mai", "dob": "2026-04-20"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["baby"]["name"] == "Mai"
    assert body["baby"]["dob"] == "2026-04-20"


def test_patch_baby_partial(client):
    client.patch("/api/babies", json={"name": "Mai"})
    client.patch("/api/babies", json={"dob": "2026-04-20"})
    # Get current baby via the home page render path (no /api/babies GET yet)
    r = client.patch("/api/babies", json={})
    body = r.json()["baby"]
    assert body["name"] == "Mai"
    assert body["dob"] == "2026-04-20"


def test_patch_baby_rejects_bad_dob(client):
    r = client.patch("/api/babies", json={"dob": "20-04-2026"})
    assert r.status_code == 422


def test_patch_baby_rejects_extra_fields(client):
    r = client.patch("/api/babies", json={"name": "Mai", "colour": "blue"})
    assert r.status_code == 422


def test_patch_baby_emits_sse(client):
    q = broker.subscribe()
    try:
        r = client.patch("/api/babies", json={"name": "Mai"})
        assert r.status_code == 200
        assert not q.empty()
        event_name, _, payload = q.get_nowait()
        assert event_name == "baby.updated"
        assert payload["name"] == "Mai"
    finally:
        broker.unsubscribe(q)


def test_patch_baby_accepts_empty_payload_as_noop(client):
    """An empty PATCH returns the current row without raising."""
    r = client.patch("/api/babies", json={})
    assert r.status_code == 200
    assert r.json()["baby"]["id"] == 1


def test_settings_routes_accept_x_device_id_header(client):
    """
    All settings routes carry `Depends(current_actor)`. Header
    presence/absence is invisible to the response today, but the
    request must succeed either way.
    """
    r_with = client.patch(
        "/api/settings",
        json={"tz": "UTC"},
        headers={"X-Device-Id": "dev-test"},
    )
    r_without = client.patch("/api/settings", json={"tz": "UTC"})
    assert r_with.status_code == 200
    assert r_without.status_code == 200
