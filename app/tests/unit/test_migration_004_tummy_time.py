"""
Migration 004 — adds the 'tummy_time' event type (v1.1.1).

Tummy time is a recurring activity with a duration. We model it as a
6th event type so it inherits the existing soft-delete + dup-detection
+ SSE + reports machinery. Session length lives in the existing
`feed_duration_min` column (column name is historical; the value just
means "duration in minutes").

Same 12-step rebuild pattern as migration 003. These tests construct
a v1.1.0-shaped DB (post-003) and run apply_pending against the real
migrations dir.
"""

from __future__ import annotations

import sqlite3

import pytest

from nbio.migrations import MIGRATIONS_DIR, apply_pending, current_version

# v1.1.0 events schema (post-003) — CHECK is the 5-type set.
POST_003_SCHEMA = """
CREATE TABLE IF NOT EXISTS babies (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    dob         TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS devices (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    color       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS events (
    id                  INTEGER PRIMARY KEY,
    baby_id             INTEGER NOT NULL REFERENCES babies(id),
    type                TEXT NOT NULL CHECK (type IN ('breast','formula','wee','poo','vitd')),
    occurred_at         TEXT NOT NULL,
    feed_side           TEXT CHECK (feed_side IN ('L','R','both') OR feed_side IS NULL),
    feed_duration_min   INTEGER,
    poo_quality         INTEGER,
    notes               TEXT,
    idempotency_key     TEXT NOT NULL,
    created_by_device   TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at          TEXT,
    formula_brand       TEXT,
    formula_volume_ml   INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_events_idem ON events(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_events_baby_time ON events(baby_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_events_dup_window
    ON events(baby_id, type, occurred_at) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS app_settings (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    tz          TEXT,
    notes_md    TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT OR IGNORE INTO app_settings (id) VALUES (1);
"""


@pytest.fixture
def post_003_db():
    """In-memory DB at user_version=3 (post-migration-003)."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(POST_003_SCHEMA)
    c.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")
    c.execute("PRAGMA user_version = 3")
    yield c
    c.close()


def test_migration_004_expands_type_check_to_include_tummy_time(post_003_db):
    """After migration 004, inserting type='tummy_time' must succeed."""
    apply_pending(post_003_db, MIGRATIONS_DIR)
    post_003_db.execute(
        """INSERT INTO events (type, baby_id, occurred_at, feed_duration_min,
           idempotency_key, created_by_device)
           VALUES ('tummy_time', 1, '2026-05-20T10:00:00.000Z', 5,
                   'idem-tt-1', 'dev-1')"""
    )
    row = post_003_db.execute(
        "SELECT type, feed_duration_min FROM events WHERE idempotency_key='idem-tt-1'"
    ).fetchone()
    assert row["type"] == "tummy_time"
    assert row["feed_duration_min"] == 5


def test_migration_004_still_rejects_unknown_types(post_003_db):
    """The CHECK widens to include 'tummy_time' — random other types still rejected."""
    apply_pending(post_003_db, MIGRATIONS_DIR)
    with pytest.raises(sqlite3.IntegrityError):
        post_003_db.execute(
            """INSERT INTO events (type, baby_id, occurred_at, idempotency_key,
               created_by_device)
               VALUES ('exercise', 1, '2026-05-20T10:00:00.000Z',
                       'idem-bad', 'dev-1')"""
        )


def test_migration_004_preserves_existing_events(post_003_db):
    """Pre-existing rows (including vitd from #003) survive the rebuild."""
    rows = [
        (
            "breast",
            "2026-05-16T03:00:00.000Z",
            "L",
            15,
            None,
            "idem-pre-1",
            "dev-1",
        ),
        (
            "vitd",
            "2026-05-16T09:00:00.000Z",
            None,
            None,
            None,
            "idem-pre-2",
            "dev-1",
        ),
        (
            "poo",
            "2026-05-16T10:00:00.000Z",
            None,
            None,
            4,
            "idem-pre-3",
            "dev-1",
        ),
    ]
    for r in rows:
        post_003_db.execute(
            """INSERT INTO events (type, baby_id, occurred_at, feed_side,
               feed_duration_min, poo_quality, idempotency_key,
               created_by_device)
               VALUES (?, 1, ?, ?, ?, ?, ?, ?)""",
            r,
        )
    apply_pending(post_003_db, MIGRATIONS_DIR)
    after = post_003_db.execute("SELECT type, idempotency_key FROM events ORDER BY id").fetchall()
    assert [r["type"] for r in after] == ["breast", "vitd", "poo"]
    assert [r["idempotency_key"] for r in after] == [
        "idem-pre-1",
        "idem-pre-2",
        "idem-pre-3",
    ]


def test_migration_004_recreates_indexes(post_003_db):
    """All three event indexes survive the rebuild."""
    apply_pending(post_003_db, MIGRATIONS_DIR)
    names = {
        r["name"]
        for r in post_003_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'"
        )
    }
    assert "ux_events_idem" in names
    assert "ix_events_baby_time" in names
    assert "ix_events_dup_window" in names


def test_migration_004_advances_user_version_past_4(post_003_db):
    assert current_version(post_003_db) == 3
    apply_pending(post_003_db, MIGRATIONS_DIR)
    assert current_version(post_003_db) >= 4


def test_migration_004_idempotent_on_rerun(post_003_db):
    apply_pending(post_003_db, MIGRATIONS_DIR)
    v = current_version(post_003_db)
    apply_pending(post_003_db, MIGRATIONS_DIR)
    assert current_version(post_003_db) == v
    # And we can still insert tummy_time events.
    post_003_db.execute(
        """INSERT INTO events (type, baby_id, occurred_at, feed_duration_min,
           idempotency_key, created_by_device)
           VALUES ('tummy_time', 1, '2026-05-20T11:00:00.000Z', 3,
                   'idem-tt-rerun', 'dev-1')"""
    )
