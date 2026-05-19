-- 006_feed_duration_sec.sql — adds INTEGER seconds column for sub-minute
-- precision on duration-bearing events (tummy time timer especially).
--
-- The existing `feed_duration_min` column stays — used by breast feeds
-- and as a fallback for legacy tummy_time rows that pre-date this
-- migration. New tummy_time rows from the timer write seconds and may
-- leave `feed_duration_min` NULL; aggregations COALESCE seconds first.
--
-- Purely additive — no rebuild, no CHECK changes, no data migration.
-- Tracking: v1.1.1 follow-up — timer recording <1min as "1 min" was
-- imprecise.

PRAGMA foreign_keys = OFF;
BEGIN;

ALTER TABLE events ADD COLUMN feed_duration_sec INTEGER;

COMMIT;
PRAGMA foreign_keys = ON;
