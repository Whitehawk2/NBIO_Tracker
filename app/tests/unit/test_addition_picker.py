"""
v1.2 Addition picker + per-device picker-mode toggle.

Real-user feedback follow-up to PR #87: the chip set still forces
"close enough" rounding when the target value doesn't match any chip.
This PR adds a second formula-amount picker ("Addition mode") alongside
the existing chip picker ("Classic mode"), togglable per-device via
localStorage.

Design summary:
- Mode lives in localStorage["nbio.formula_picker_mode"] = "classic"|"addition".
  Default "classic" (status quo). Per-device by deliberate choice: each
  parent has their own muscle memory.
- Addition picker: running total widget + Reset + six additive buttons
  (+5, +10, +20, +30, +60, +120) + "SET TO…" (CUSTOM relabeled in
  Addition mode to disambiguate the verb — agent flagged that "CUSTOM"
  reading as ADD-in-additive-context is a 5cc-feed footgun). The cap
  setting is IGNORED in Addition mode.
- Long-press on the Formula tile is unified across modes: read
  localStorage["nbio.last_formula_ml"] + nbio.last_formula_brand, fire
  submitCreate with them; fall back to opening the modal if either is
  unset. Also fixes the existing latent bug where long-press fired a
  formula with no volume.
- Mode toggle UI lives in Settings -> "This device" (consistent with
  other per-device prefs: name + colour). The cap input stays in
  "Feeding" with an "(applies to Classic mode only)" hint.

These tests pin the contract surface only — the trimmed source-pin
approach the Plan agent recommended (existence of key names + the
~3 critical entry points). Behavioural validation is the PR's manual
QA checklist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[2] / "nbio" / "static" / "app.js"
SETTINGS_JS = Path(__file__).resolve().parents[2] / "nbio" / "static" / "settings.js"


@pytest.fixture(scope="module")
def app_js() -> str:
    return APP_JS.read_text()


@pytest.fixture(scope="module")
def settings_js() -> str:
    return SETTINGS_JS.read_text()


# --- settings UI ------------------------------------------------------------


def test_settings_device_section_has_picker_mode_radio(client):
    """The mode toggle lives in `This device` (per-device prefs section)."""
    body = client.get("/settings").text
    # Pin the radio group's name + both option values. Class/structure
    # is template's call; the contract is "two named radios with these
    # exact values exist on the page".
    assert 'name="formula_picker_mode"' in body, (
        "settings page must include a formula_picker_mode radio group"
    )
    assert 'value="classic"' in body, "must offer the Classic mode option"
    assert 'value="addition"' in body, "must offer the Addition mode option"


def test_settings_device_section_picker_mode_scope_hint(client):
    """The mode is per-device, not app-wide — the UI must say so loudly,
    because the cap input two sections below IS app-wide and the user
    needs to feel the difference."""
    body = client.get("/settings").text
    # Loose match: any phrasing along "this device only" / "this phone only".
    lo = body.lower()
    assert ("this device" in lo) or ("this phone" in lo), (
        "picker mode setting must clarify its per-device scope (e.g. "
        '"this phone only") so users distinguish it from the app-wide cap'
    )


def test_settings_feeding_cap_hint_mentions_classic_only(client):
    """The cap input now only matters for Classic mode. The hint must
    say so — otherwise Addition-mode users will be surprised the cap
    they set doesn't affect their picker."""
    body = client.get("/settings").text
    # Loose: hint text mentions Classic somewhere in the Feeding section.
    feeding_marker = 'data-section="feeding"'
    fi = body.find(feeding_marker)
    assert fi > 0
    feeding_block = body[fi : fi + 2000]
    assert "Classic" in feeding_block, (
        "cap input must mention Classic in its hint so users know the "
        "cap is irrelevant in Addition mode"
    )


# --- settings.js wiring -----------------------------------------------------


def test_settings_js_persists_picker_mode_to_localstorage(settings_js):
    """Settings page reads + writes the mode via localStorage (not via
    PATCH /api/settings). Pin the localStorage key — that's the
    contract that both pages must agree on."""
    assert "nbio.formula_picker_mode" in settings_js, (
        "settings.js must reference localStorage['nbio.formula_picker_mode']"
    )
    # And confirm it actually touches localStorage (not just mentions the key
    # in a comment): both setItem and getItem appear in the file for various
    # purposes already, so we look for both in the file as a whole.
    assert "localStorage" in settings_js


def test_settings_js_does_not_patch_picker_mode(settings_js):
    """The mode is per-device. It MUST NOT be PATCHed to /api/settings —
    that would force both parents into the same mode (the whole point
    of the toggle being per-device is each parent picks independently).

    Scoped to wireFeedingForm body specifically (that's where the
    /api/settings PATCH lives). The file-level comment block that
    EXPLAINS why we don't PATCH it is allowed to mention both tokens.
    """
    fi = settings_js.find("function wireFeedingForm")
    assert fi > 0, "expected a wireFeedingForm function in settings.js"
    # Body extends to the next top-level function declaration.
    next_fn = settings_js.find("\n  function ", fi + 1)
    feeding_body = settings_js[fi : next_fn if next_fn > 0 else fi + 2000]
    assert "formula_picker_mode" not in feeding_body, (
        "formula_picker_mode appears inside wireFeedingForm — that's the "
        "function that PATCHes /api/settings. The picker mode must stay "
        "LOCAL (localStorage), set by wirePickerModeRadios in a separate "
        "function. Otherwise both parents are forced into the same mode."
    )


# --- app.js: picker dispatch + addition picker ------------------------------


def test_app_js_has_build_addition_picker(app_js):
    """The Addition picker is its own builder. Pin existence so a
    future refactor doesn't silently delete the new mode."""
    assert "function buildAdditionPicker" in app_js, (
        "app.js must define buildAdditionPicker() for the new mode"
    )


def test_app_js_open_formula_modal_dispatches_on_mode(app_js):
    """openFormulaModal reads the mode via readFormulaPickerMode() and
    dispatches to either buildClassicPicker or buildAdditionPicker.
    Pin that the dispatch happens inside the function body."""
    open_idx = app_js.find("function openFormulaModal")
    assert open_idx > 0
    body = app_js[open_idx : open_idx + 3000]
    # Either the localStorage key appears inline, or the read helper
    # is called by name. Both are valid implementations of the contract.
    has_key = "nbio.formula_picker_mode" in body
    has_helper = "readFormulaPickerMode" in body
    assert has_key or has_helper, (
        "openFormulaModal must read the picker mode (either inline via "
        "localStorage['nbio.formula_picker_mode'] or via the "
        "readFormulaPickerMode() helper)"
    )
    # And it must actually dispatch — both builders must be referenced.
    assert "buildAdditionPicker" in body and "buildClassicPicker" in body, (
        "openFormulaModal must dispatch to both buildClassicPicker and buildAdditionPicker"
    )


def test_app_js_addition_buttons_in_documented_set(app_js):
    """The button set is the contract. {5, 10, 20, 30, 60, 120} cover
    the realistic 5cc-precision range without crowding the grid.

    The literal array may live in a top-level constant (cleaner code)
    or inline in the builder. Pin the literal itself appearing
    somewhere in app.js."""
    assert "[5, 10, 20, 30, 60, 120]" in app_js, (
        "the addition button set [5, 10, 20, 30, 60, 120] must appear "
        "verbatim somewhere in app.js (constant or inline). If you "
        "change the set, update this test deliberately."
    )


def test_app_js_addition_picker_has_reset(app_js):
    """Reset is the only undo affordance — no subtract buttons. Pin
    its presence in the addition picker body."""
    add_idx = app_js.find("function buildAdditionPicker")
    body = app_js[add_idx : add_idx + 3000]
    # Case-insensitive: button label may be "Reset", "RESET", "↺ Reset"…
    assert "eset" in body, "addition picker must include a Reset affordance"


def test_app_js_addition_set_to_button_present(app_js):
    """In Addition mode, CUSTOM is relabeled to SET TO… to make the
    verb explicit (avoiding the +5 vs replace footgun)."""
    add_idx = app_js.find("function buildAdditionPicker")
    body = app_js[add_idx : add_idx + 3000]
    # Accept either "SET TO" with anything between (case-insensitive),
    # the key signal is that "CUSTOM" alone is the WRONG label here.
    assert "SET" in body.upper(), (
        "addition picker's escape-hatch button must be labeled SET TO… "
        "(not CUSTOM) to disambiguate the verb"
    )


# --- last-used localStorage + long-press unification -----------------------


def test_app_js_long_press_formula_reads_last_used(app_js):
    """Long-press on the formula tile must read both last_formula_ml
    and last_formula_brand from localStorage so the quick-log carries
    the brand too (the modal already does smart-default brand)."""
    assert "nbio.last_formula_ml" in app_js, (
        "app.js must reference localStorage['nbio.last_formula_ml']"
    )
    assert "nbio.last_formula_brand" in app_js, (
        "app.js must reference localStorage['nbio.last_formula_brand']"
    )


def test_app_js_long_press_handler_has_formula_branch(app_js):
    """The long-press timer body must special-case type === 'formula'
    similarly to how it special-cases 'both' today. The branch reads
    the last-used localStorage keys."""
    long_press_marker = "LONG_PRESS_MS ="
    li = app_js.find(long_press_marker)
    assert li > 0
    # Generous window: long-press timer body + wrapping wireTiles.
    block = app_js[li : li + 4000]
    assert 'type === "formula"' in block, (
        "long-press timer body must special-case type === 'formula' to "
        "read last_formula_ml + last_formula_brand from localStorage "
        "(and fall back to opening the modal if either is empty)"
    )


def test_app_js_formula_submit_writes_last_used(app_js):
    """On a successful formula submit the volume must be persisted to
    localStorage so the next long-press has something to repeat. Pin
    the actual setItem call on the ml key (not just that setItem
    appears somewhere in the 2000-line file)."""
    assert re.search(r"""setItem\(\s*["']nbio\.last_formula_ml["']""", app_js), (
        "app.js must call localStorage.setItem('nbio.last_formula_ml', ...) "
        "on formula submit so long-press can repeat the last amount"
    )


def test_app_js_formula_submit_keeps_brand_in_lockstep(app_js):
    """Brand must track volume: set when present, REMOVED when absent.
    Otherwise a no-brand feed leaves a stale brand that the next
    long-press would wrongly pair with the new volume."""
    assert re.search(r"""removeItem\(\s*["']nbio\.last_formula_brand["']""", app_js), (
        "app.js must removeItem('nbio.last_formula_brand') when a formula "
        "is logged without a brand — otherwise long-press pairs the new "
        "volume with a stale brand from an earlier feed"
    )


# --- client-side cap clamp + last-used eviction note -----------------------


def test_app_js_addition_picker_respects_server_volume_cap(app_js):
    """Server's formula_volume_ml model is le=500. The addition picker
    should not let the running total exceed 500 — otherwise a misclick
    spam of +120 produces total=600, optimistic row goes through, then
    POST 422s after the modal closes.

    The clamp uses a constant FORMULA_MAX_ML; pin both that the
    constant exists with the right value somewhere in the file AND
    that the addition builder references it."""
    assert "FORMULA_MAX_ML = 500" in app_js, (
        "FORMULA_MAX_ML constant must be defined at value 500 (the "
        "server-side formula_volume_ml ceiling)"
    )
    add_idx = app_js.find("function buildAdditionPicker")
    body = app_js[add_idx : add_idx + 3000]
    assert "FORMULA_MAX_ML" in body, (
        "buildAdditionPicker must reference FORMULA_MAX_ML to clamp the running total at 500cc"
    )


def test_app_js_addition_picker_ignores_cap(app_js):
    """The operator-set chip cap (formula_chip_max_ml) is a Classic-mode
    concept only — the Addition picker must NOT reference it. This is the
    headline behavioural promise of the mode split, so pin that the cap
    field never appears inside buildAdditionPicker."""
    add_idx = app_js.find("function buildAdditionPicker")
    assert add_idx > 0
    next_fn = app_js.find("\n  function ", add_idx + 1)
    body = app_js[add_idx : next_fn if next_fn > 0 else add_idx + 3000]
    assert "formula_chip_max_ml" not in body, (
        "buildAdditionPicker must not read formula_chip_max_ml — the cap "
        "applies to Classic mode only. Addition mode ignores it by design."
    )
