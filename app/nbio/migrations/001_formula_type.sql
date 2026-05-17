-- 001_formula_type.sql — adds formula event type + brand/volume columns
--
-- This rebuilds the `events` table to:
--   * expand the type CHECK from ('feed','wee','poo') to
--     ('breast','formula','wee','poo')
--   * rename all existing rows with type='feed' to type='breast'
--   * add two new nullable columns: formula_brand TEXT, formula_volume_ml INTEGER
--
-- SQLite can't ALTER CHECK constraints in place, so this is the
-- standard "12-step" table rebuild (CREATE new, INSERT-SELECT, DROP old,
-- RENAME, recreate indexes). Wrapped in a transaction so a failure
-- mid-flight leaves the original `events` intact.
--
-- Tracking: issue #28 finding #5.

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE events_new (
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

INSERT INTO events_new (
    id, baby_id, type, occurred_at, feed_side, feed_duration_min, poo_quality,
    notes, idempotency_key, created_by_device, created_at, updated_at, deleted_at,
    formula_brand, formula_volume_ml
)
SELECT
    id,
    baby_id,
    CASE WHEN type = 'feed' THEN 'breast' ELSE type END,
    occurred_at,
    feed_side,
    feed_duration_min,
    poo_quality,
    notes,
    idempotency_key,
    created_by_device,
    created_at,
    updated_at,
    deleted_at,
    NULL,
    NULL
FROM events;

DROP TABLE events;
ALTER TABLE events_new RENAME TO events;

-- Recreate the three indexes from the original schema.
CREATE UNIQUE INDEX IF NOT EXISTS ux_events_idem ON events(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_events_baby_time ON events(baby_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_events_dup_window
    ON events(baby_id, type, occurred_at) WHERE deleted_at IS NULL;

COMMIT;
PRAGMA foreign_keys = ON;
