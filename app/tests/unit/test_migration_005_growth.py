"""
Migration 005 — adds the `growth` table (v1.1.1 weight tracking).

Purely additive — no rebuild required. Tests verify the column shape
(weight_g + length_mm + head_circ_mm columns, the last two nullable
and unwired in v1.1.1 per issue #55), the idempotency unique index +
soft-delete column from day 1, user_version advance, and idempotent
re-run.
"""

from __future__ import annotations

import sqlite3

import pytest

from nbio.migrations import MIGRATIONS_DIR, apply_pending, current_version

# v1.1.0 + 004 schema (pre-005).
POST_004_SCHEMA = """
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
    type                TEXT NOT NULL CHECK (type IN ('breast','formula','wee','poo','vitd','tummy_time')),
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

CREATE TABLE IF NOT EXISTS app_settings (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    tz          TEXT,
    notes_md    TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT OR IGNORE INTO app_settings (id) VALUES (1);
"""


@pytest.fixture
def post_004_db():
    """In-memory DB at user_version=4 (post-migration-004)."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(POST_004_SCHEMA)
    c.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")
    c.execute("PRAGMA user_version = 4")
    yield c
    c.close()


def test_migration_005_creates_growth_table(post_004_db):
    apply_pending(post_004_db, MIGRATIONS_DIR)
    cols = {row["name"] for row in post_004_db.execute("PRAGMA table_info(growth)")}
    # The four metric columns (weight + two #55-forward-compat + notes).
    assert "weight_g" in cols
    assert "length_mm" in cols
    assert "head_circ_mm" in cols
    assert "notes" in cols
    # Soft-delete + idempotency + audit columns.
    assert "idempotency_key" in cols
    assert "deleted_at" in cols
    assert "created_by_device" in cols
    assert "measured_at" in cols


def test_migration_005_idempotency_index_created(post_004_db):
    apply_pending(post_004_db, MIGRATIONS_DIR)
    indexes = {
        row["name"]
        for row in post_004_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='growth'"
        )
    }
    assert "ux_growth_idem" in indexes
    assert "ix_growth_baby_time" in indexes


def test_migration_005_weight_check_rejects_obvious_typo(post_004_db):
    """A weight of 30001g (30kg+) hits the CHECK constraint."""
    apply_pending(post_004_db, MIGRATIONS_DIR)
    with pytest.raises(sqlite3.IntegrityError):
        post_004_db.execute(
            """INSERT INTO growth (baby_id, measured_at, weight_g,
               idempotency_key, created_by_device)
               VALUES (1, '2026-05-16', 30001, 'idem-bad', 'dev-1')"""
        )


def test_migration_005_accepts_reasonable_newborn_weight(post_004_db):
    apply_pending(post_004_db, MIGRATIONS_DIR)
    post_004_db.execute(
        """INSERT INTO growth (baby_id, measured_at, weight_g,
           idempotency_key, created_by_device)
           VALUES (1, '2026-05-16', 3420, 'idem-good', 'dev-1')"""
    )
    row = post_004_db.execute(
        "SELECT weight_g FROM growth WHERE idempotency_key='idem-good'"
    ).fetchone()
    assert row["weight_g"] == 3420


def test_migration_005_advances_user_version_past_4(post_004_db):
    assert current_version(post_004_db) == 4
    apply_pending(post_004_db, MIGRATIONS_DIR)
    assert current_version(post_004_db) >= 5


def test_migration_005_idempotent_on_rerun(post_004_db):
    apply_pending(post_004_db, MIGRATIONS_DIR)
    v = current_version(post_004_db)
    apply_pending(post_004_db, MIGRATIONS_DIR)
    assert current_version(post_004_db) == v
    # Can still insert.
    post_004_db.execute(
        """INSERT INTO growth (baby_id, measured_at, weight_g,
           idempotency_key, created_by_device)
           VALUES (1, '2026-05-17', 3500, 'idem-rerun', 'dev-1')"""
    )


def test_migration_005_idempotency_key_unique(post_004_db):
    apply_pending(post_004_db, MIGRATIONS_DIR)
    post_004_db.execute(
        """INSERT INTO growth (baby_id, measured_at, weight_g,
           idempotency_key, created_by_device)
           VALUES (1, '2026-05-16', 3420, 'idem-dup', 'dev-1')"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        post_004_db.execute(
            """INSERT INTO growth (baby_id, measured_at, weight_g,
               idempotency_key, created_by_device)
               VALUES (1, '2026-05-17', 3500, 'idem-dup', 'dev-1')"""
        )
