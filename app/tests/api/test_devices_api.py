"""/api/devices* — list + upsert."""


def test_list_empty(client):
    assert client.get("/api/devices").json() == {"devices": []}


def test_upsert_creates_device(client):
    r = client.put("/api/devices/dev-1", json={"name": "Mum", "color": "#4F8BFF"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["device"]["id"] == "dev-1"
    assert body["device"]["color"] == "#4F8BFF"


def test_upsert_updates_existing(client):
    client.put("/api/devices/dev-1", json={"name": "Mum", "color": "#4F8BFF"})
    r = client.put("/api/devices/dev-1", json={"name": "Mom", "color": "#FF00AA"})
    assert r.json()["device"]["color"] == "#FF00AA"
    # Still only one row
    assert len(client.get("/api/devices").json()["devices"]) == 1


def test_upsert_rejects_bad_color(client):
    r = client.put("/api/devices/dev-1", json={"color": "not-a-hex"})
    assert r.status_code == 422


def test_list_returns_all_devices(client):
    client.put("/api/devices/dev-a", json={"color": "#aaaaaa"})
    client.put("/api/devices/dev-b", json={"color": "#bbbbbb"})
    ids = [d["id"] for d in client.get("/api/devices").json()["devices"]]
    assert set(ids) == {"dev-a", "dev-b"}
