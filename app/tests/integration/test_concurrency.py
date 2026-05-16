"""
Real concurrent writes to a WAL-enabled file-backed SQLite via
httpx.AsyncClient + ASGITransport + asyncio.gather.

TestClient is single-threaded so we can't exercise WAL there. Here the
file DB + multiple async POSTs exercises BEGIN IMMEDIATE + busy_timeout.
"""

import asyncio

import httpx
import pytest
from httpx import ASGITransport


def _payload(idem):
    return {
        "type": "feed",
        "occurred_at": "2026-05-16T03:00:00.000Z",
        "idempotency_key": idem,
        "created_by_device": "device-test",
    }


@pytest.mark.asyncio
async def test_distinct_idem_keys_all_create(tmp_db_path):
    """10 parallel POSTs with distinct idem → 10 rows, no errors."""
    import sqlite3

    from nbio.db import SCHEMA, get_conn
    from nbio.main import app

    # Bootstrap the file DB once.
    c0 = sqlite3.connect(str(tmp_db_path), isolation_level=None)
    c0.execute("PRAGMA journal_mode=WAL")
    c0.executescript(SCHEMA)
    c0.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")
    c0.close()

    def _override():
        conn = sqlite3.connect(
            str(tmp_db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            tasks = [ac.post("/api/events", json=_payload(f"idem-conc-{i:04d}")) for i in range(10)]
            results = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in results)
        statuses = [r.json()["status"] for r in results]
        # All 10 should be 'created' (or possibly 'created_possible_duplicate'
        # since they share the same occurred_at — that's fine).
        assert all(s in {"created", "created_possible_duplicate"} for s in statuses)
        # 10 distinct rows in the DB
        check = sqlite3.connect(str(tmp_db_path))
        try:
            cnt = check.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            check.close()
        assert cnt == 10
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_same_idem_key_yields_single_row(tmp_db_path):
    """10 parallel POSTs with the SAME idem → exactly 1 row total."""
    import sqlite3

    from nbio.db import SCHEMA, get_conn
    from nbio.main import app

    c0 = sqlite3.connect(str(tmp_db_path), isolation_level=None)
    c0.execute("PRAGMA journal_mode=WAL")
    c0.executescript(SCHEMA)
    c0.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")
    c0.close()

    def _override():
        conn = sqlite3.connect(
            str(tmp_db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            tasks = [
                ac.post("/api/events", json=_payload("idem-same-key-shared")) for _ in range(10)
            ]
            results = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in results)
        # Mix of "created" (1) and "already_exists" (9). All point at the same id.
        ids = {r.json()["event"]["id"] for r in results}
        assert ids == {1}
        # And explicit shape: 1 created, 9 already_exists — not 5xx, not a
        # mix of partial states (the recovery branch fires for the losers).
        statuses = [r.json()["status"] for r in results]
        assert statuses.count("created") == 1
        assert statuses.count("already_exists") == 9
        check = sqlite3.connect(str(tmp_db_path))
        try:
            cnt = check.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            check.close()
        assert cnt == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_same_row_parallel_patches_serialize_cleanly(tmp_db_path):
    """
    BEGIN IMMEDIATE + busy_timeout=5000 should let N parallel PATCHes of
    the same row succeed without SQLITE_BUSY leaking to the client, and
    the final row state is one of the values we wrote (not NULL, not a
    stale stack-leak).

    The row-count tests above would pass with BEGIN DEFERRED — the
    UNIQUE idempotency index alone guarantees they would. This test
    demonstrates the *write serialization* property that BEGIN IMMEDIATE
    actually buys us (issue #21, critical gap 3).
    """
    import sqlite3

    from nbio.db import SCHEMA, get_conn
    from nbio.main import app

    c0 = sqlite3.connect(str(tmp_db_path), isolation_level=None)
    c0.execute("PRAGMA journal_mode=WAL")
    c0.executescript(SCHEMA)
    c0.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")
    c0.close()

    def _override():
        conn = sqlite3.connect(
            str(tmp_db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            seed = await ac.post("/api/events", json=_payload("idem-seed-contention"))
            assert seed.status_code == 200
            row_id = seed.json()["event"]["id"]

            n = 10
            tasks = [
                ac.patch(f"/api/events/{row_id}", json={"notes": f"writer-{i:02d}"})
                for i in range(n)
            ]
            results = await asyncio.gather(*tasks)

        statuses = [r.status_code for r in results]
        assert statuses.count(200) == n, f"got statuses {statuses}"

        check = sqlite3.connect(str(tmp_db_path))
        try:
            final = check.execute("SELECT notes FROM events WHERE id = ?", (row_id,)).fetchone()[0]
            cnt = check.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            check.close()

        assert final is not None
        assert final.startswith("writer-"), f"final notes value isn't one of ours: {final!r}"
        assert cnt == 1, "spurious INSERT under PATCH contention"
    finally:
        app.dependency_overrides.clear()
