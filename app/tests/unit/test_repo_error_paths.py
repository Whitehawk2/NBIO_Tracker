"""
Forced-failure ROLLBACK branches. Uses conftest's `FailingConn` proxy
(moved there in #21 so other tests can import it without a cross-test
import).
"""

import sqlite3

import pytest

from nbio.models import DeviceUpsert, EventCreate, EventPatch
from nbio.repo import (
    create_event,
    patch_event,
    soft_delete_event,
    undelete_event,
    upsert_device,
)
from tests.conftest import FailingConn


def _seed(conn):
    p = EventCreate(
        type="breast",
        occurred_at="2026-05-16T03:00:00.000Z",
        idempotency_key="idem-seed-row",
        created_by_device="device-1",
    )
    _, event, _ = create_event(conn, p)
    return event


def test_patch_event_rollback_on_failure(conn):
    event = _seed(conn)
    proxy = FailingConn(conn, "UPDATE events SET")
    with pytest.raises(sqlite3.OperationalError):
        patch_event(proxy, event["id"], EventPatch(notes="late"))
    row = conn.execute("SELECT notes FROM events WHERE id=?", (event["id"],)).fetchone()
    assert row["notes"] is None


def test_soft_delete_rollback_on_failure(conn):
    event = _seed(conn)
    proxy = FailingConn(conn, "UPDATE events SET deleted_at = ?")
    with pytest.raises(sqlite3.OperationalError):
        soft_delete_event(proxy, event["id"])
    row = conn.execute("SELECT deleted_at FROM events WHERE id=?", (event["id"],)).fetchone()
    assert row["deleted_at"] is None


def test_undelete_rollback_on_failure(conn):
    event = _seed(conn)
    soft_delete_event(conn, event["id"])
    proxy = FailingConn(conn, "UPDATE events SET deleted_at = NULL")
    with pytest.raises(sqlite3.OperationalError):
        undelete_event(proxy, event["id"])
    row = conn.execute("SELECT deleted_at FROM events WHERE id=?", (event["id"],)).fetchone()
    assert row["deleted_at"] is not None


def test_upsert_device_rollback_on_failure(conn):
    proxy = FailingConn(conn, "INSERT INTO devices")
    with pytest.raises(sqlite3.OperationalError):
        upsert_device(proxy, "dev-x", DeviceUpsert(color="#aabbcc"))
    cnt = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    assert cnt == 0
