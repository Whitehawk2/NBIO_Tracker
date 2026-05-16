"""/api/version — exposes the static-assets hash for diagnostics + the JS."""

import re


def test_version_endpoint_returns_a_hash(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"version"}
    assert re.fullmatch(r"[0-9a-f]{12}", body["version"])


def test_version_endpoint_matches_static_assets_hash(client):
    """The endpoint and the SW route must agree on the version."""
    from nbio.version import static_assets_hash

    r = client.get("/api/version")
    assert r.json()["version"] == static_assets_hash()
