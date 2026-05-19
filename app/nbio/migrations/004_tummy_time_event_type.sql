-- 004_tummy_time_event_type.sql — adds 'tummy_time' to the events.type CHECK.
--
-- Tummy time is a daily activity — pediatric guidance is 3-5 minute
-- sessions, several times a day. We model it as a 6th event type
-- (alongside breast / formula / wee / poo / vitd). Session length is
-- stored in the existing `feed_duration_min` column (the column is not
-- breast-specific in practice — it just means "duration in minutes").
--
-- SQLite can't ALTER CHECK in place; standard 12-step table rebuild.
-- Wrapped in a transaction so a failure mid-flight leaves the original
-- `events` intact.
--
-- Tracking: v1.1.1 — tummy time tracking.

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE events_new (
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

INSERT INTO events_new (
    id, baby_id, type, occurred_at, feed_side, feed_duration_min,
    poo_quality, notes, idempotency_key, created_by_device,
    created_at, updated_at, deleted_at, formula_brand, formula_volume_ml
)
SELECT
    id, baby_id, type, occurred_at, feed_side, feed_duration_min,
    poo_quality, notes, idempotency_key, created_by_device,
    created_at, updated_at, deleted_at, formula_brand, formula_volume_ml
FROM events;

DROP TABLE events;
ALTER TABLE events_new RENAME TO events;

CREATE UNIQUE INDEX IF NOT EXISTS ux_events_idem ON events(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_events_baby_time ON events(baby_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_events_dup_window
    ON events(baby_id, type, occurred_at) WHERE deleted_at IS NULL;

COMMIT;
PRAGMA foreign_keys = ON;
