"""
Migration 003 — adds the 'vitd' event type (closes #8.5 / v1.1.0 ask).

Pediatric guidance is one drop of Vit D per day. Existing types
(breast / formula / wee / poo) are many-per-day; vit D is the first
once-daily type, but the data shape is identical (occurred_at + actor
+ optional notes). Treat as a 5th event type with NO new columns.

SQLite can't ALTER a CHECK constraint in place, so this is the
standard 12-step rebuild — same pattern as migration 001.

These tests construct a v1.x-shaped DB (post-002) and run apply_pending
against the real migrations dir. They cover: CHECK widened, existing
events preserved, indexes recreated, user_version advance, idempotency.
"""

from __future__ import annotations

import sqlite3

import pytest

from nbio.migrations import MIGRATIONS_DIR, apply_pending, current_version

# v1.x events schema — post-002 (events has formula_brand + formula_volume_ml,
# CHECK is the v1.0.x set, app_settings table exists).
POST_002_SCHEMA = """
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

CREATE TABLE IF NOT EXISTS app_settings (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    tz          TEXT,
    notes_md    TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT OR IGNORE INTO app_settings (id) VALUES (1);
"""


@pytest.fixture
def post_002_db():
    """In-memory DB at user_version=2 (post-migration-002)."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(POST_002_SCHEMA)
    c.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")
    c.execute("PRAGMA user_version = 2")
    yield c
    c.close()


def test_migration_003_expands_type_check_to_include_vitd(post_002_db):
    """After migration 003, inserting type='vitd' must succeed."""
    apply_pending(post_002_db, MIGRATIONS_DIR)
    post_002_db.execute(
        """INSERT INTO events (type, baby_id, occurred_at, idempotency_key, created_by_device)
           VALUES ('vitd', 1, '2026-05-20T09:00:00.000Z', 'idem-vitd-1', 'dev-1')"""
    )
    row = post_002_db.execute("SELECT type FROM events WHERE idempotency_key='idem-vitd-1'").fetchone()
    assert row["type"] == "vitd"


def test_migration_003_still_rejects_unknown_types(post_002_db):
    """The CHECK only widens to include 'vitd' — random other types still rejected."""
    apply_pending(post_002_db, MIGRATIONS_DIR)
    with pytest.raises(sqlite3.IntegrityError):
        post_002_db.execute(
            """INSERT INTO events (type, baby_id, occurred_at, idempotency_key, created_by_device)
               VALUES ('multivitamin', 1, '2026-05-20T09:00:00.000Z', 'idem-bad', 'dev-1')"""
        )


def test_migration_003_preserves_existing_events(post_002_db):
    """Pre-existing rows survive the rebuild verbatim."""
    rows = [
        ("breast", "2026-05-16T03:00:00.000Z", "L", 15, None, "good", "idem-pre-1", "dev-1", "M", 100),
        ("formula", "2026-05-16T06:00:00.000Z", None, None, None, None, "idem-pre-2", "dev-1", "M", 80),
        ("wee", "2026-05-16T08:00:00.000Z", None, None, None, None, "idem-pre-3", "dev-1", None, None),
        ("poo", "2026-05-16T10:00:00.000Z", None, None, 4, "soft", "idem-pre-4", "dev-1", None, None),
    ]
    for r in rows:
        post_002_db.execute(
            """INSERT INTO events (type, baby_id, occurred_at, feed_side,
               feed_duration_min, poo_quality, notes, idempotency_key,
               created_by_device, formula_brand, formula_volume_ml)
               VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            r,
        )
    apply_pending(post_002_db, MIGRATIONS_DIR)
    after = post_002_db.execute(
        """SELECT type, idempotency_key, formula_brand, formula_volume_ml
           FROM events ORDER BY id"""
    ).fetchall()
    assert len(after) == 4
    assert [r["type"] for r in after] == ["breast", "formula", "wee", "poo"]
    assert [r["idempotency_key"] for r in after] == ["idem-pre-1", "idem-pre-2", "idem-pre-3", "idem-pre-4"]
    # Formula row keeps brand + volume.
    formula_row = next(r for r in after if r["type"] == "formula")
    assert formula_row["formula_brand"] == "M"
    assert formula_row["formula_volume_ml"] == 80


def test_migration_003_recreates_indexes(post_002_db):
    """All three event indexes survive the rebuild."""
    apply_pending(post_002_db, MIGRATIONS_DIR)
    names = {
        r["name"]
        for r in post_002_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'"
        )
    }
    assert "ux_events_idem" in names
    assert "ix_events_baby_time" in names
    assert "ix_events_dup_window" in names


def test_migration_003_advances_user_version_to_3(post_002_db):
    assert current_version(post_002_db) == 2
    apply_pending(post_002_db, MIGRATIONS_DIR)
    assert current_version(post_002_db) == 3


def test_migration_003_idempotent_on_rerun(post_002_db):
    apply_pending(post_002_db, MIGRATIONS_DIR)
    apply_pending(post_002_db, MIGRATIONS_DIR)
    assert current_version(post_002_db) == 3
    # And we can still insert vitd events.
    post_002_db.execute(
        """INSERT INTO events (type, baby_id, occurred_at, idempotency_key, created_by_device)
           VALUES ('vitd', 1, '2026-05-20T10:00:00.000Z', 'idem-vitd-rerun', 'dev-1')"""
    )
