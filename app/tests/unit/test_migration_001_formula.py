"""
Migration 001 — adds 'formula' event type + formula_brand/formula_volume_ml
columns + renames legacy type='feed' rows to type='breast'.

These tests construct an old-shape DB (the v0.9.0 schema, before this PR)
and then run `apply_pending` pointed at the real `nbio/migrations/`
directory. Asserts cover data preservation, the type rename, the new
columns, the new CHECK constraint, and index preservation.
"""

from __future__ import annotations

import sqlite3

import pytest

from nbio.migrations import MIGRATIONS_DIR, apply_pending, current_version

# v0.9.0 events schema — what an upgrading install starts with.
OLD_SCHEMA = """
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
    type                TEXT NOT NULL CHECK (type IN ('feed','wee','poo')),
    occurred_at         TEXT NOT NULL,
    feed_side           TEXT CHECK (feed_side IN ('L','R','both') OR feed_side IS NULL),
    feed_duration_min   INTEGER,
    poo_quality         INTEGER,
    notes               TEXT,
    idempotency_key     TEXT NOT NULL,
    created_by_device   TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at          TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_events_idem ON events(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_events_baby_time ON events(baby_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_events_dup_window
    ON events(baby_id, type, occurred_at) WHERE deleted_at IS NULL;
"""


@pytest.fixture
def old_db():
    """A connection to an in-memory DB seeded with the v0.9.0 schema."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(OLD_SCHEMA)
    c.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")
    yield c
    c.close()


def _seed_legacy_events(conn):
    """Insert one of each legacy type, plus a soft-deleted row for completeness."""
    rows = [
        # (type, occurred_at, feed_side, feed_duration_min, poo_quality, notes, idem, dev)
        ("feed", "2026-05-16T03:00:00.000Z", "L", 15, None, "good", "idem-feed-1", "dev-1"),
        ("feed", "2026-05-16T06:00:00.000Z", "R", 12, None, None, "idem-feed-2", "dev-1"),
        ("wee", "2026-05-16T03:30:00.000Z", None, None, None, None, "idem-wee-1", "dev-1"),
        ("poo", "2026-05-16T04:00:00.000Z", None, None, 4, "soft", "idem-poo-1", "dev-1"),
    ]
    for r in rows:
        conn.execute(
            """INSERT INTO events (type, baby_id, occurred_at, feed_side,
               feed_duration_min, poo_quality, notes, idempotency_key,
               created_by_device)
               VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)""",
            r,
        )
    # And one soft-deleted feed row
    conn.execute(
        """INSERT INTO events (type, baby_id, occurred_at, feed_side, idempotency_key,
           created_by_device, deleted_at)
           VALUES ('feed', 1, '2026-05-15T22:00:00.000Z', 'both',
                   'idem-deleted-1', 'dev-1', '2026-05-15T23:00:00.000Z')""",
    )


def test_001_migration_advances_user_version(old_db):
    assert current_version(old_db) == 0
    applied = apply_pending(old_db, MIGRATIONS_DIR)
    assert 1 in applied
    assert current_version(old_db) >= 1


def test_001_migration_renames_feed_to_breast(old_db):
    _seed_legacy_events(old_db)
    apply_pending(old_db, MIGRATIONS_DIR)

    # No 'feed' rows remain
    feed_count = old_db.execute("SELECT COUNT(*) FROM events WHERE type='feed'").fetchone()[0]
    assert feed_count == 0

    # All previously-feed rows are now 'breast' (including soft-deleted)
    breast_count = old_db.execute("SELECT COUNT(*) FROM events WHERE type='breast'").fetchone()[0]
    assert breast_count == 3  # 2 active feeds + 1 deleted feed

    # Other types untouched
    assert old_db.execute("SELECT COUNT(*) FROM events WHERE type='wee'").fetchone()[0] == 1
    assert old_db.execute("SELECT COUNT(*) FROM events WHERE type='poo'").fetchone()[0] == 1


def test_001_migration_preserves_row_count_and_ids(old_db):
    _seed_legacy_events(old_db)
    pre_count = old_db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    pre_ids = {r[0] for r in old_db.execute("SELECT id FROM events")}

    apply_pending(old_db, MIGRATIONS_DIR)

    post_count = old_db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    post_ids = {r[0] for r in old_db.execute("SELECT id FROM events")}
    assert post_count == pre_count
    assert post_ids == pre_ids


def test_001_migration_preserves_feed_side_and_duration(old_db):
    _seed_legacy_events(old_db)
    apply_pending(old_db, MIGRATIONS_DIR)
    row = old_db.execute(
        "SELECT feed_side, feed_duration_min FROM events WHERE idempotency_key='idem-feed-1'"
    ).fetchone()
    assert row["feed_side"] == "L"
    assert row["feed_duration_min"] == 15


def test_001_migration_preserves_deleted_at(old_db):
    _seed_legacy_events(old_db)
    apply_pending(old_db, MIGRATIONS_DIR)
    row = old_db.execute(
        "SELECT type, deleted_at FROM events WHERE idempotency_key='idem-deleted-1'"
    ).fetchone()
    assert row["type"] == "breast"
    assert row["deleted_at"] == "2026-05-15T23:00:00.000Z"


def test_001_migration_adds_formula_columns(old_db):
    apply_pending(old_db, MIGRATIONS_DIR)
    cols = {row["name"] for row in old_db.execute("PRAGMA table_info(events)")}
    assert "formula_brand" in cols
    assert "formula_volume_ml" in cols


def test_001_migration_formula_columns_are_null_on_legacy_rows(old_db):
    _seed_legacy_events(old_db)
    apply_pending(old_db, MIGRATIONS_DIR)
    row = old_db.execute(
        "SELECT formula_brand, formula_volume_ml FROM events WHERE idempotency_key='idem-feed-1'"
    ).fetchone()
    assert row["formula_brand"] is None
    assert row["formula_volume_ml"] is None


def test_001_migration_expands_type_check_to_include_formula(old_db):
    """After migration, INSERT with type='formula' must succeed (CHECK passes)."""
    apply_pending(old_db, MIGRATIONS_DIR)
    old_db.execute(
        """INSERT INTO events (type, baby_id, occurred_at, idempotency_key,
           created_by_device, formula_brand, formula_volume_ml)
           VALUES ('formula', 1, '2026-05-16T05:00:00.000Z', 'idem-new-formula',
                   'dev-1', 'Materna', 120)""",
    )
    row = old_db.execute(
        "SELECT type, formula_brand, formula_volume_ml FROM events "
        "WHERE idempotency_key='idem-new-formula'"
    ).fetchone()
    assert row["type"] == "formula"
    assert row["formula_brand"] == "Materna"
    assert row["formula_volume_ml"] == 120


def test_001_migration_still_rejects_legacy_feed_type_after_migration(old_db):
    """After migration, INSERT with type='feed' should fail the CHECK."""
    apply_pending(old_db, MIGRATIONS_DIR)
    with pytest.raises(sqlite3.IntegrityError):
        old_db.execute(
            """INSERT INTO events (type, baby_id, occurred_at, idempotency_key,
               created_by_device)
               VALUES ('feed', 1, '2026-05-16T05:00:00.000Z', 'idem-bad-feed', 'dev-1')""",
        )


def test_001_migration_preserves_all_indexes(old_db):
    apply_pending(old_db, MIGRATIONS_DIR)
    indexes = {
        row[0]
        for row in old_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert "ux_events_idem" in indexes
    assert "ix_events_baby_time" in indexes
    assert "ix_events_dup_window" in indexes


def test_001_migration_keeps_idem_unique(old_db):
    """The UNIQUE constraint on idempotency_key must survive the rebuild."""
    _seed_legacy_events(old_db)
    apply_pending(old_db, MIGRATIONS_DIR)
    with pytest.raises(sqlite3.IntegrityError):
        old_db.execute(
            """INSERT INTO events (type, baby_id, occurred_at, idempotency_key,
               created_by_device)
               VALUES ('wee', 1, '2026-05-16T05:00:00.000Z',
                       'idem-feed-1',  -- already used by the legacy seed
                       'dev-1')""",
        )


def test_001_migration_idempotent_on_new_shape(tmp_path):
    """
    Running pending migrations against a DB already at the latest
    user_version is a no-op. As new migrations land, bump the version
    in this test to match the highest .sql file in the migrations dir.
    """
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    # Simulate a fresh install at the latest user_version (post-004).
    c.execute("PRAGMA user_version = 4")
    applied = apply_pending(c, MIGRATIONS_DIR)
    assert applied == []
    c.close()


def test_001_migration_handles_empty_events_table(old_db):
    """Old-shape DB with no rows — migration runs cleanly."""
    # Sanity: events table is empty
    assert old_db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    apply_pending(old_db, MIGRATIONS_DIR)
    # New schema in place; still empty
    cols = {row["name"] for row in old_db.execute("PRAGMA table_info(events)")}
    assert "formula_brand" in cols
    assert old_db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
