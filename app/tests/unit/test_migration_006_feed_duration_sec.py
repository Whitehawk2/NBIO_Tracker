"""
Migration 006 — adds `feed_duration_sec` column to events for
sub-minute precision (v1.1.1 follow-up: tummy timer recorded <1min
sessions as "1 min" because of the INTEGER minutes column).

Purely additive — no rebuild, no CHECK changes, no data migration.
"""

from __future__ import annotations

import sqlite3

import pytest

from nbio.migrations import MIGRATIONS_DIR, apply_pending, current_version

# v1.1.1 events schema (post-005) — has the 6-type CHECK including tummy_time,
# but no feed_duration_sec column yet.
POST_005_SCHEMA = """
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
    type                TEXT NOT NULL CHECK (type IN (
        'breast','formula','wee','poo','vitd','tummy_time'
    )),
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

CREATE TABLE IF NOT EXISTS growth (
    id                INTEGER PRIMARY KEY,
    baby_id           INTEGER NOT NULL REFERENCES babies(id),
    measured_at       TEXT NOT NULL,
    weight_g          INTEGER CHECK (weight_g IS NULL OR weight_g BETWEEN 0 AND 30000),
    length_mm         INTEGER,
    head_circ_mm      INTEGER,
    notes             TEXT,
    idempotency_key   TEXT NOT NULL,
    created_by_device TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at        TEXT
);
"""


@pytest.fixture
def post_005_db():
    """In-memory DB at user_version=5 (post-migration-005)."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(POST_005_SCHEMA)
    c.execute("INSERT INTO babies (id, name) VALUES (1, 'Test Baby')")
    c.execute("PRAGMA user_version = 5")
    yield c
    c.close()


def test_migration_006_adds_feed_duration_sec_column(post_005_db):
    apply_pending(post_005_db, MIGRATIONS_DIR)
    cols = {row["name"] for row in post_005_db.execute("PRAGMA table_info(events)")}
    assert "feed_duration_sec" in cols


def test_migration_006_accepts_seconds_value(post_005_db):
    apply_pending(post_005_db, MIGRATIONS_DIR)
    post_005_db.execute(
        """INSERT INTO events (type, baby_id, occurred_at, feed_duration_sec,
           idempotency_key, created_by_device)
           VALUES ('tummy_time', 1, '2026-05-20T10:00:00.000Z', 35,
                   'idem-tt-sec', 'dev-1')"""
    )
    row = post_005_db.execute(
        "SELECT feed_duration_sec FROM events WHERE idempotency_key='idem-tt-sec'"
    ).fetchone()
    assert row["feed_duration_sec"] == 35


def test_migration_006_preserves_pre_existing_rows(post_005_db):
    """Rows without feed_duration_sec keep working — column defaults to NULL."""
    post_005_db.execute(
        """INSERT INTO events (type, baby_id, occurred_at, feed_duration_min,
           idempotency_key, created_by_device)
           VALUES ('tummy_time', 1, '2026-05-15T08:00:00.000Z', 5,
                   'idem-tt-legacy', 'dev-1')"""
    )
    apply_pending(post_005_db, MIGRATIONS_DIR)
    row = post_005_db.execute(
        "SELECT feed_duration_min, feed_duration_sec FROM events "
        "WHERE idempotency_key='idem-tt-legacy'"
    ).fetchone()
    assert row["feed_duration_min"] == 5
    assert row["feed_duration_sec"] is None


def test_migration_006_advances_user_version_past_5(post_005_db):
    assert current_version(post_005_db) == 5
    apply_pending(post_005_db, MIGRATIONS_DIR)
    assert current_version(post_005_db) >= 6


def test_migration_006_idempotent_on_rerun(post_005_db):
    apply_pending(post_005_db, MIGRATIONS_DIR)
    v = current_version(post_005_db)
    apply_pending(post_005_db, MIGRATIONS_DIR)
    assert current_version(post_005_db) == v
