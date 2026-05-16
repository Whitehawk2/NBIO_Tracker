"""
Shared fixtures.

DB strategy: most tests use the in-memory `conn` fixture; concurrency / WAL
tests use the file-backed `tmp_db_path` + `tmp_db_conn` pair.

Broker strategy: `nbio.sse.broker` is a module-level singleton imported by
reference into `routes/{events,devices,stream}.py`. We mutate its internal
state per test rather than replacing the instance — rebinding the module
attribute would not update the already-imported names.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

# Force UTC for every test so _local_hhmm / _group_events_by_local_day
# are deterministic regardless of where CI runs. Set before any nbio import.
os.environ.setdefault("TZ", "UTC")


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Apply the production schema to a connection and seed baby id=1."""
    from nbio.db import SCHEMA

    conn.executescript(SCHEMA)
    row = conn.execute("SELECT id FROM babies LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")


def _open_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        path,
        check_same_thread=False,
        isolation_level=None,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """Fresh in-memory SQLite with schema applied and baby seeded."""
    c = _open_conn(":memory:")
    _apply_schema(c)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """File path for a fresh SQLite DB (WAL-mode capable)."""
    return tmp_path / "test.db"


@pytest.fixture
def tmp_db_conn(tmp_db_path: Path) -> Iterator[sqlite3.Connection]:
    """File-backed SQLite connection with WAL enabled and schema applied."""
    c = _open_conn(str(tmp_db_path))
    c.execute("PRAGMA journal_mode=WAL")
    _apply_schema(c)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture(autouse=True)
def reset_broker():
    """
    Clear the singleton broker's subscriber set before and after every test.
    We mutate state, not replace the instance — see module docstring.
    """
    from nbio import sse

    sse.broker._subs.clear()
    yield
    sse.broker._subs.clear()


@pytest.fixture
def client(conn):
    """
    FastAPI TestClient with `get_conn` overridden to yield the test conn.
    Used as a context manager so the lifespan handler runs.
    """
    from fastapi.testclient import TestClient

    from nbio.db import get_conn
    from nbio.main import app

    def _override():
        try:
            yield conn
        finally:
            pass  # connection lifetime is owned by the `conn` fixture

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def event_payload():
    """Factory returning a dict suitable for POST /api/events."""

    def make(**overrides):
        base = {
            "type": "feed",
            "occurred_at": "2026-05-16T03:00:00.000Z",
            "feed_side": "L",
            "feed_duration_min": 15,
            "idempotency_key": "test-idem-key-0001",
            "created_by_device": "device-test",
        }
        base.update(overrides)
        return base

    return make


@pytest.fixture
def seed_event(conn):
    """Insert an event directly via repo.create_event; return the dict."""
    from nbio.models import EventCreate
    from nbio.repo import create_event

    def make(**overrides):
        defaults = {
            "type": "feed",
            "occurred_at": "2026-05-16T03:00:00.000Z",
            "feed_side": "L",
            "feed_duration_min": 15,
            "idempotency_key": f"idem-{overrides.get('_n', 0):04d}-{id(overrides):x}",
            "created_by_device": "device-test",
        }
        defaults.update({k: v for k, v in overrides.items() if not k.startswith("_")})
        payload = EventCreate(**defaults)
        _, event, _ = create_event(conn, payload)
        return event

    return make


@pytest.fixture
def anyio_backend():
    """Force asyncio backend for any AnyIO-aware tests."""
    return "asyncio"


def pytest_collection_modifyitems(config, items):
    """Mark integration tests so they can be selected/excluded easily."""
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        if "/shell/" in str(item.fspath):
            item.add_marker(pytest.mark.shell)
