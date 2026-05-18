-- 002_app_settings.sql — runtime-editable app config (closes #6 schema side)
--
-- Adds a singleton `app_settings` row (CHECK id=1) for settings that
-- belong on the server (not per-device localStorage):
--   * tz       — optional timezone override (NULL = use config.tz from env)
--   * notes_md — operator notes / forward-compat freeform slot
--
-- Purely additive — no rebuild, no FK tangle. Re-running is a no-op
-- thanks to IF NOT EXISTS + INSERT OR IGNORE.
--
-- Tracking: issue #6.

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE IF NOT EXISTS app_settings (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    tz          TEXT,
    notes_md    TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

INSERT OR IGNORE INTO app_settings (id) VALUES (1);

COMMIT;
PRAGMA foreign_keys = ON;
