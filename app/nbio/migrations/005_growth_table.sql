-- 005_growth_table.sql — adds the `growth` table for weight tracking.
--
-- Health-visitor visits and pediatric checks hinge on baby weight,
-- recorded ~weekly. NBIO didn't track this; now it does.
--
-- Schema is forward-compatible with issue #55 (full growth log + WHO
-- percentile overlay): `length_mm` and `head_circ_mm` columns are
-- nullable from day 1 but UNWIRED in v1.1.1 — only `weight_g` has UI
-- surface. This avoids a future breaking migration when #55 lands.
--
-- weight_g CHECK guards against typo (entering 34200 for a 3.42kg
-- baby) — 30kg is well above any newborn-tracker scope.
--
-- Idempotency + soft-delete from day 1 — parents WILL mistype "3420"
-- as "3240" and want undo.
--
-- Tracking: v1.1.1 — weight tracking.

PRAGMA foreign_keys = OFF;
BEGIN;

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

COMMIT;
PRAGMA foreign_keys = ON;
