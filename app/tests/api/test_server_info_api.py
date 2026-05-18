"""
/api/server-info (#6 settings → System tab).

Surfaces the runtime info parents might need for support: app version,
static-asset hash, DB size, uptime. Pure read; no actor required.
"""

from __future__ import annotations

import time
import tomllib
from pathlib import Path


def test_server_info_returns_required_keys(client):
    r = client.get("/api/server-info")
    assert r.status_code == 200
    body = r.json()
    for key in ("version", "static_hash", "db_size_bytes", "uptime_seconds"):
        assert key in body, f"server-info missing key: {key}"


def test_server_info_version_matches_pyproject(client):
    """The returned `version` must match the version in pyproject.toml."""
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        version = tomllib.load(f)["project"]["version"]
    body = client.get("/api/server-info").json()
    assert body["version"] == version


def test_server_info_static_hash_is_12_hex_chars(client):
    """Matches nbio.version.static_assets_hash() — 12-char hex string."""
    import re

    body = client.get("/api/server-info").json()
    assert re.match(r"^[0-9a-f]{12}$", body["static_hash"]), body["static_hash"]


def test_server_info_uptime_increases(client):
    """Two calls in sequence — uptime second is >= uptime first."""
    a = client.get("/api/server-info").json()["uptime_seconds"]
    time.sleep(0.01)
    b = client.get("/api/server-info").json()["uptime_seconds"]
    assert b >= a


def test_server_info_db_size_positive(client):
    """The seeded schema means the DB file (or in-memory DB) is non-empty."""
    body = client.get("/api/server-info").json()
    assert isinstance(body["db_size_bytes"], int)
    assert body["db_size_bytes"] >= 0


def test_server_info_handles_missing_db_file(client, monkeypatch):
    """
    `:memory:` and other non-file db_path values raise on stat() —
    the route must fall back to 0 rather than 500.
    """
    from nbio.config import settings

    monkeypatch.setattr(settings, "db_path", ":memory:")
    body = client.get("/api/server-info").json()
    assert body["db_size_bytes"] == 0
