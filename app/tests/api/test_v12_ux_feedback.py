"""
v1.2.0 UX iteration — real-user feedback round 1.

Three coupled asks from production:

1. Tile reorder: formula above breast on the index page (current parents
   formula-feed primarily; the dominant action should be the top tile).
2. Formula chip range:
   - Add 70 and 80 cc to the chip set (40-80 is the common newborn range
     and was previously CUSTOM-only).
   - New `app_settings.formula_chip_max_ml` that caps the top amount
     shown so 120/150/180/210/240 don't crowd the row when the baby
     hasn't grown into them yet. CUSTOM is always present regardless.
3. Combined "wee + poo" tile: one tap logs both events at the same
   `occurred_at` (real parents reported logging the two separately is
   cognitively heavy when nappy changes always reveal both).

These tests pin the server-rendered HTML contracts + the API contract
for the new setting. JS source-pins for the chip-filter and
both-handler live in `tests/unit/test_app_js_v12.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import nbio.models as models
from nbio import repo
from nbio.models import AppSettingsUpdate

# ---------------------------------------------------------------------------
# 1. Tile reorder + new "both" tile
# ---------------------------------------------------------------------------


def test_index_renders_formula_tile_before_breast(client):
    """
    Real-user feedback: families using formula primarily want the
    formula tile at the top of the column. The breast tile drops to
    second. The DOM order of the partial includes pins this.
    """
    body = client.get("/").text
    i_formula = body.find('class="tile tile-formula"')
    i_breast = body.find('class="tile tile-breast"')
    assert i_formula != -1, "tile-formula must render on /"
    assert i_breast != -1, "tile-breast must render on /"
    assert i_formula < i_breast, (
        "formula tile must appear before breast tile in DOM order "
        f"(formula at {i_formula}, breast at {i_breast})"
    )


def test_index_renders_both_tile_after_wee_and_poo(client):
    """
    The new "both" tile (wee + poo in one tap) lives at the bottom of
    the quick-log column, below wee and poo.
    """
    body = client.get("/").text
    i_wee = body.find('class="tile tile-wee"')
    i_poo = body.find('class="tile tile-poo"')
    i_both = body.find('class="tile tile-both"')
    assert i_both != -1, "tile-both must render on /"
    assert i_both > i_wee, "tile-both must appear after tile-wee"
    assert i_both > i_poo, "tile-both must appear after tile-poo"
    # The button label must clearly say BOTH so the user knows what fires.
    assert 'data-type="both"' in body, 'tile-both must carry data-type="both"'
    assert ">BOTH<" in body, "tile-both must show a 'BOTH' label"


def test_index_tile_grid_has_five_tiles(client):
    """Five tiles: formula, breast, wee, poo, both."""
    body = client.get("/").text
    count = body.count('class="tile tile-')
    assert count == 5, f"expected 5 quick-log tiles, got {count}"


# ---------------------------------------------------------------------------
# 2. Formula chip cap setting
# ---------------------------------------------------------------------------


def test_app_settings_update_model_accepts_formula_chip_max_ml():
    """The pydantic model accepts a value in the sane range."""
    AppSettingsUpdate(formula_chip_max_ml=80)
    AppSettingsUpdate(formula_chip_max_ml=10)
    AppSettingsUpdate(formula_chip_max_ml=500)


def test_app_settings_update_model_accepts_null_to_clear_cap():
    """None on the field means 'no cap, show all chips'."""
    m = AppSettingsUpdate(formula_chip_max_ml=None)
    assert m.formula_chip_max_ml is None


@pytest.mark.parametrize("bad", [0, 5, 9, 501, 1000, -1])
def test_app_settings_update_model_rejects_out_of_range(bad):
    """Below 10 cc or above 500 cc is rejected at the model layer."""
    with pytest.raises(Exception):  # noqa: B017 — ValidationError, but model is the contract
        AppSettingsUpdate(formula_chip_max_ml=bad)


def test_repo_app_settings_read_returns_formula_chip_max_ml_default_none(conn):
    """Fresh DB → the cap is None (no chip filtering)."""
    row = repo.app_settings_read(conn)
    assert "formula_chip_max_ml" in row, "app_settings_read must expose the new column"
    assert row["formula_chip_max_ml"] is None


def test_repo_app_settings_update_persists_formula_chip_max_ml(conn):
    repo.app_settings_update(conn, AppSettingsUpdate(formula_chip_max_ml=80))
    assert repo.app_settings_read(conn)["formula_chip_max_ml"] == 80


def test_repo_app_settings_partial_update_preserves_cap(conn):
    """Sending only notes_md must NOT blank out a previously-set cap."""
    repo.app_settings_update(conn, AppSettingsUpdate(formula_chip_max_ml=80))
    repo.app_settings_update(conn, AppSettingsUpdate(notes_md="unrelated note"))
    row = repo.app_settings_read(conn)
    assert row["formula_chip_max_ml"] == 80, "PATCH on notes_md must not clear the cap"
    assert row["notes_md"] == "unrelated note"


def test_patch_settings_with_cap_persists_and_returns_row(client):
    r = client.patch("/api/settings", json={"formula_chip_max_ml": 80})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["settings"]["formula_chip_max_ml"] == 80
    # Re-fetch via GET to confirm persistence.
    g = client.get("/api/settings").json()
    assert g["settings"]["formula_chip_max_ml"] == 80


def test_patch_settings_can_clear_cap(client):
    """Explicit null clears a previously-set cap."""
    client.patch("/api/settings", json={"formula_chip_max_ml": 80})
    r = client.patch("/api/settings", json={"formula_chip_max_ml": None})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["formula_chip_max_ml"] is None


def test_patch_settings_rejects_out_of_range_cap(client):
    """422 (pydantic) on values outside the [10, 500] range."""
    r = client.patch("/api/settings", json={"formula_chip_max_ml": 5})
    assert r.status_code == 422, r.text
    r = client.patch("/api/settings", json={"formula_chip_max_ml": 600})
    assert r.status_code == 422, r.text


def test_get_settings_includes_formula_chip_max_ml(client):
    """The GET endpoint exposes the new field (used by app.js at boot)."""
    body = client.get("/api/settings").json()
    assert "formula_chip_max_ml" in body["settings"], (
        "GET /api/settings must include formula_chip_max_ml so the "
        "client can apply the cap to the quick-log chip row"
    )
    assert body["settings"]["formula_chip_max_ml"] is None  # default


def test_settings_page_renders_feeding_section_with_cap_input(client):
    """Settings UI exposes the new cap as a numeric input."""
    body = client.get("/settings").text
    assert 'data-section="feeding"' in body, (
        "settings page must include a Feeding <details> section"
    )
    assert 'id="formula-chip-max-ml"' in body, "Feeding section must include the cap input"
    # Min/max bracket the model-layer validation so the browser-side
    # constraint and server-side constraint stay in sync.
    assert 'min="10"' in body and 'max="500"' in body


def test_settings_page_cap_input_prefills_existing_value(client):
    """If the cap is set, the input pre-fills with the current value."""
    client.patch("/api/settings", json={"formula_chip_max_ml": 80})
    body = client.get("/settings").text
    # The value attribute should carry "80" inside the formula-chip-max-ml input.
    import re

    m = re.search(
        r'<input[^>]*id="formula-chip-max-ml"[^>]*>',
        body,
    )
    assert m, "could not find the cap input"
    assert 'value="80"' in m.group(0), (
        f"cap input must pre-fill with the current value; got: {m.group(0)}"
    )


# ---------------------------------------------------------------------------
# 3. Notes from the previous app_settings test surface stay green
# ---------------------------------------------------------------------------
# (covered by the existing test_settings_api.py — no duplication here.)


# ---------------------------------------------------------------------------
# Sanity: the AppSettingsUpdate model still rejects unknown fields.
# (Extra-forbid is critical for the patch_settings_rejects_extra_fields test
# elsewhere; the new field must not loosen that.)
# ---------------------------------------------------------------------------


def test_app_settings_update_still_rejects_unknown_fields():
    with pytest.raises(Exception):  # noqa: B017
        AppSettingsUpdate.model_validate({"nonsense_field": 1})


# ---------------------------------------------------------------------------
# Migration 007 contract
# ---------------------------------------------------------------------------


def test_migration_007_file_exists():
    """The migration file is committed and lives in the migrations dir."""
    root = Path(models.__file__).resolve().parent
    p = root / "migrations" / "007_formula_chip_max_ml.sql"
    assert p.is_file(), f"expected migration file at {p}"
    sql = p.read_text()
    assert "ALTER TABLE app_settings" in sql
    assert "formula_chip_max_ml" in sql
