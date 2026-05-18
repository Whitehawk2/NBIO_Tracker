"""
`auth.current_actor` — future-auth seam (#6).

Today this resolves an Actor from the `X-Device-Id` header (or returns
an anonymous Actor when the header is missing or the device is
unknown). Future session / JWT auth replaces the body but keeps the
`Depends(current_actor)` signature so route code doesn't churn.

Pin the contract:
- known device id → device-kind Actor with the device's name + color
- missing header → anonymous Actor (kind='anonymous', id='anon')
- unknown device id → anonymous Actor (don't 401 today; routes are
  read-tolerant)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from nbio.auth import current_actor
from nbio.db import get_conn
from nbio.models import Actor


@pytest.fixture
def actor_app(conn):
    """A throwaway FastAPI app whose only route returns the resolved Actor."""
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(req: Request) -> dict:
        # Manually invoke current_actor with the conn fixture so we don't
        # need to bring up the full app. FastAPI's Depends wiring is
        # already exercised by the route tests later; this isolates the
        # resolver logic.
        actor = await current_actor(req, conn)
        return actor.model_dump()

    app.dependency_overrides[get_conn] = lambda: conn
    return TestClient(app)


def test_current_actor_uses_x_device_id_header(actor_app, conn):
    """A known device id → device-kind Actor with name + color populated."""
    conn.execute("INSERT INTO devices (id, name, color) VALUES ('dev-mum', 'Mum', '#4F8BFF')")
    r = actor_app.get("/whoami", headers={"X-Device-Id": "dev-mum"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "dev-mum"
    assert body["kind"] == "device"
    assert body["name"] == "Mum"
    assert body["color"] == "#4F8BFF"


def test_current_actor_anonymous_when_header_missing(actor_app):
    """No X-Device-Id header → anonymous Actor."""
    r = actor_app.get("/whoami")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "anonymous"
    assert body["id"] == "anon"
    assert body["name"] is None
    assert body["color"] is None


def test_current_actor_anonymous_when_device_unknown(actor_app):
    """Unknown device id → anonymous (don't 401; settings routes are read-tolerant)."""
    r = actor_app.get("/whoami", headers={"X-Device-Id": "dev-ghost"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "anonymous"
    assert body["id"] == "anon"


def test_current_actor_typed_as_actor(actor_app, conn):
    """The /whoami response shape must match the Actor model exactly."""
    conn.execute("INSERT INTO devices (id, name, color) VALUES ('dev-dad', 'Dad', '#9B6BFF')")
    r = actor_app.get("/whoami", headers={"X-Device-Id": "dev-dad"})
    # Round-trip through Pydantic — body must be a valid Actor.
    actor = Actor(**r.json())
    assert actor.kind == "device"
    assert actor.id == "dev-dad"
    assert actor.name == "Dad"
    assert actor.color == "#9B6BFF"
