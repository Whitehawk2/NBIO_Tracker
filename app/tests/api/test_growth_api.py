"""
/api/growth — weight tracking (v1.1.1).

CRUD + SSE round-trip. The growth router is new in v1.1.1; events
mirror the events broker namespace (growth.created / .updated /
.deleted / .undeleted).
"""

from __future__ import annotations


def _payload(**over):
    base = {
        "measured_at": "2026-05-16",
        "weight_g": 3420,
        "idempotency_key": "idem-grow-aa",
        "created_by_device": "device-test",
    }
    base.update(over)
    return base


def test_post_growth_succeeds(client):
    r = client.post("/api/growth", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "created"
    assert body["growth"]["weight_g"] == 3420


def test_post_growth_rejects_typo_weight(client):
    """weight_g > 30000 fails validation (Pydantic) before hitting the DB."""
    r = client.post("/api/growth", json=_payload(weight_g=34200))
    assert r.status_code == 422


def test_post_growth_rejects_bad_date_format(client):
    """measured_at must be YYYY-MM-DD."""
    r = client.post("/api/growth", json=_payload(measured_at="May 16, 2026"))
    assert r.status_code == 422


def test_get_growth_round_trips(client):
    created = client.post("/api/growth", json=_payload(idempotency_key="idem-grow-rt")).json()
    growth_id = created["growth"]["id"]
    r = client.get(f"/api/growth/{growth_id}")
    assert r.status_code == 200
    assert r.json()["growth"]["weight_g"] == 3420


def test_list_growth_returns_asc(client):
    """List endpoint returns rows ASC by measured_at (chart-friendly)."""
    client.post(
        "/api/growth",
        json=_payload(measured_at="2026-05-22", weight_g=3500, idempotency_key="idem-grow-b"),
    )
    client.post(
        "/api/growth",
        json=_payload(measured_at="2026-05-15", weight_g=3300, idempotency_key="idem-grow-a"),
    )
    r = client.get("/api/growth")
    assert r.status_code == 200
    rows = r.json()["growth"]
    assert [row["measured_at"] for row in rows] == ["2026-05-15", "2026-05-22"]


def test_patch_growth(client):
    created = client.post("/api/growth", json=_payload(idempotency_key="idem-grow-patch")).json()
    growth_id = created["growth"]["id"]
    r = client.patch(f"/api/growth/{growth_id}", json={"weight_g": 3520})
    assert r.status_code == 200
    assert r.json()["growth"]["weight_g"] == 3520


def test_delete_growth_soft_deletes(client):
    created = client.post("/api/growth", json=_payload(idempotency_key="idem-grow-del")).json()
    growth_id = created["growth"]["id"]
    r = client.delete(f"/api/growth/{growth_id}")
    assert r.status_code == 200
    # The row is fetchable but flagged.
    body = client.get(f"/api/growth/{growth_id}").json()
    assert body["growth"]["deleted_at"] is not None
    # It's removed from the default list.
    list_body = client.get("/api/growth").json()
    assert list_body["growth"] == []


def test_undelete_growth(client):
    created = client.post("/api/growth", json=_payload(idempotency_key="idem-grow-undel")).json()
    growth_id = created["growth"]["id"]
    client.delete(f"/api/growth/{growth_id}")
    r = client.post(f"/api/growth/{growth_id}/undelete")
    assert r.status_code == 200
    assert r.json()["growth"]["deleted_at"] is None


def test_idempotent_post(client):
    """Same idempotency_key twice → second hits the dup path."""
    p = _payload(idempotency_key="idem-grow-dup")
    r1 = client.post("/api/growth", json=p)
    r2 = client.post("/api/growth", json=p)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_exists"


def test_get_missing_404(client):
    r = client.get("/api/growth/999")
    assert r.status_code == 404


def test_patch_missing_404(client):
    r = client.patch("/api/growth/999", json={"weight_g": 3500})
    assert r.status_code == 404


def test_delete_missing_404(client):
    r = client.delete("/api/growth/999")
    assert r.status_code == 404
