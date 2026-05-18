"""
Migration 002 — adds the singleton `app_settings` table for runtime-
editable configuration (closes #6 schema side).

The table holds settings that DON'T fit per-device localStorage (TZ
override, operator notes) and that survive container restarts. It's
seeded with a single id=1 row at migration time so `app_settings_read`
never returns None.

These tests construct a v1.x-shaped DB (post-001) and then run
`apply_pending` against the real migrations dir. They cover: table
creation, the singleton seed, idempotency on re-run, and the
`PRAGMA user_version` advance.
"""

from __future__ import annotations

import sqlite3

import pytest

from nbio.migrations import MIGRATIONS_DIR, apply_pending, current_version


# v1.x events schema — what an install upgrading from v1.0.x has at
# user_version=1 (post-001).
POST_001_SCHEMA = """
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
    type                TEXT NOT NULL CHECK (type IN ('breast','formula','wee','poo')),
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
"""


@pytest.fixture
def post_001_db():
    """A connection to an in-memory DB at user_version=1 (post-migration-001)."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(POST_001_SCHEMA)
    c.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")
    c.execute("PRAGMA user_version = 1")  # mark 001 as already applied
    yield c
    c.close()


def test_migration_002_creates_app_settings_table(post_001_db):
    """app_settings must exist with the documented columns after running 002."""
    apply_pending(post_001_db, MIGRATIONS_DIR)
    cols = {
        row["name"]
        for row in post_001_db.execute("PRAGMA table_info(app_settings)")
    }
    assert cols == {"id", "tz", "notes_md", "updated_at"}, (
        f"unexpected app_settings columns: {cols}"
    )


def test_migration_002_seeds_singleton_row(post_001_db):
    """A single id=1 row exists so app_settings_read never returns None."""
    apply_pending(post_001_db, MIGRATIONS_DIR)
    rows = list(post_001_db.execute("SELECT id, tz, notes_md FROM app_settings"))
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["tz"] is None
    assert rows[0]["notes_md"] is None


def test_migration_002_id_is_constrained_to_1(post_001_db):
    """The id=1 CHECK constraint blocks accidental multi-row inserts."""
    apply_pending(post_001_db, MIGRATIONS_DIR)
    with pytest.raises(sqlite3.IntegrityError):
        post_001_db.execute("INSERT INTO app_settings (id) VALUES (2)")


def test_migration_002_idempotent_on_rerun(post_001_db):
    """Running apply_pending twice is a no-op for already-applied versions."""
    apply_pending(post_001_db, MIGRATIONS_DIR)
    rows_first = list(post_001_db.execute("SELECT * FROM app_settings"))
    apply_pending(post_001_db, MIGRATIONS_DIR)
    rows_second = list(post_001_db.execute("SELECT * FROM app_settings"))
    assert len(rows_first) == 1 and len(rows_second) == 1
    assert dict(rows_first[0]) == dict(rows_second[0])


def test_migration_002_advances_user_version_to_2(post_001_db):
    """user_version ticks 1 → 2 once 002 runs."""
    assert current_version(post_001_db) == 1
    apply_pending(post_001_db, MIGRATIONS_DIR)
    assert current_version(post_001_db) == 2


def test_migration_002_existing_data_preserved(post_001_db):
    """Adding app_settings doesn't touch babies / devices / events."""
    post_001_db.execute(
        "INSERT INTO devices (id, name, color) VALUES ('dev-1', 'Mum', '#4F8BFF')"
    )
    post_001_db.execute(
        """INSERT INTO events (type, baby_id, occurred_at, idempotency_key, created_by_device)
           VALUES ('wee', 1, '2026-05-16T03:00:00.000Z', 'idem-pre-002', 'dev-1')"""
    )
    apply_pending(post_001_db, MIGRATIONS_DIR)
    assert (
        post_001_db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
    )
    assert (
        post_001_db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    )
    assert (
        post_001_db.execute("SELECT name FROM babies WHERE id=1").fetchone()[0]
        == "Test Baby"
    )
