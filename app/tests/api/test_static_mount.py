"""Validate the StaticFiles mount in main.py."""


def test_static_app_js_200(client):
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert (
        "javascript" in r.headers["content-type"].lower()
        or "application" in r.headers["content-type"].lower()
    )


def test_static_manifest_200(client):
    r = client.get("/static/manifest.webmanifest")
    assert r.status_code == 200


def test_static_unknown_404(client):
    r = client.get("/static/nope-not-here.txt")
    assert r.status_code == 404
