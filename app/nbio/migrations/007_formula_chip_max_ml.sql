-- 007_formula_chip_max_ml.sql — adds an INTEGER setting that caps the
-- top amount shown on the formula quick-log chip row.
--
-- NULL (default) = no cap; the client shows the full volChoices array
-- including the 120/150/180/210/240 cc chips. Setting it to e.g. 80
-- hides everything above 80, reducing cognitive load + misclicks for
-- newborns who currently take 40-80 cc per feed. CUSTOM is always
-- present regardless of cap.
--
-- Purely additive — no rebuild, no CHECK changes, no data migration.

PRAGMA foreign_keys = OFF;
BEGIN;

ALTER TABLE app_settings ADD COLUMN formula_chip_max_ml INTEGER;

COMMIT;
PRAGMA foreign_keys = ON;
