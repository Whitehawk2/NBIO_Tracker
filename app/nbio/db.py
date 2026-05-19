import sqlite3
from collections.abc import Iterator
from pathlib import Path

from .config import settings

SCHEMA = """
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

CREATE TABLE IF NOT EXISTS growth (
    id                INTEGER PRIMARY KEY,
    baby_id           INTEGER NOT NULL REFERENCES babies(id),
    measured_at       TEXT NOT NULL,
    weight_g          INTEGER CHECK (weight_g IS NULL OR weight_g BETWEEN 0 AND 30000),
    length_mm         INTEGER,
    head_circ_mm     INTEGER,
    notes             TEXT,
    idempotency_key   TEXT NOT NULL,
    created_by_device TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_growth_idem ON growth(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_growth_baby_time ON growth(baby_id, measured_at DESC);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(
        settings.db_path,
        check_same_thread=False,
        isolation_level=None,  # autocommit; we open BEGIN IMMEDIATE explicitly
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    from . import migrations

    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT id FROM babies LIMIT 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO babies (id, name) VALUES (1, ?)",
                (settings.baby_name,),
            )
        # Run any pending schema migrations after the baseline SCHEMA so
        # in-place upgrades reach the same shape new installs already have.
        # No-op on fresh installs (user_version advances; rebuild is empty).
        migrations.apply_pending(conn)
    finally:
        conn.close()


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency. One connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
