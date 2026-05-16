"""Idempotency-key behaviour: the front-line dedup."""

from unittest.mock import patch

import pytest

from nbio.models import EventCreate
from nbio.repo import create_event, fetch_event_by_idem


def _payload(**over):
    base = {
        "type": "feed",
        "occurred_at": "2026-05-16T03:00:00.000Z",
        "idempotency_key": "idem-shared",
        "created_by_device": "device-1",
    }
    base.update(over)
    return EventCreate(**base)


def test_same_idem_returns_existing(conn):
    s1, e1, _ = create_event(conn, _payload())
    s2, e2, _ = create_event(conn, _payload(occurred_at="2026-05-16T04:00:00.000Z"))
    assert s1 == "created"
    assert s2 == "already_exists"
    assert e1["id"] == e2["id"]
    # The second call doesn't update the row
    assert e2["occurred_at"] == e1["occurred_at"]


def test_distinct_idem_keys_yield_distinct_rows(conn):
    create_event(conn, _payload(idempotency_key="idem-a-pad"))
    create_event(conn, _payload(idempotency_key="idem-b-pad"))
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_race_loser_returns_already_exists(conn):
    """
    Simulate the race: pre-INSERT idem lookup missed but the INSERT raised
    IntegrityError because another writer inserted the same key in the gap.
    The recovery branch re-fetches and returns 'already_exists'.
    """
    create_event(conn, _payload(idempotency_key="idem-race"))
    real_row = fetch_event_by_idem(conn, "idem-race")
    with patch("nbio.repo.fetch_event_by_idem") as f:
        # First call (pre-INSERT lookup) returns None → forces INSERT path.
        # Second call (post-IntegrityError recovery) returns the real row.
        f.side_effect = [None, real_row]
        status, event, _ = create_event(conn, _payload(idempotency_key="idem-race"))
    assert status == "already_exists"
    assert event["id"] == real_row["id"]


def test_create_reraises_on_non_idem_integrity_error(conn):
    """
    If IntegrityError fires post-INSERT and the idem row genuinely isn't
    present, we re-raise (covers the `existing is None: raise` branch).
    """
    import sqlite3

    from tests.unit.test_repo_error_paths import FailingConn

    proxy = FailingConn(
        conn,
        "INSERT INTO events",
        exc=sqlite3.IntegrityError("simulated non-idem unique failure"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        create_event(proxy, _payload(idempotency_key="idem-brandnew"))
