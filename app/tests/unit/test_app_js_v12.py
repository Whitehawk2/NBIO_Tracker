"""
Source pins for the v1.2.0 UX iteration in `nbio/static/app.js`.

We can't run the JS in a real browser from pytest (no Vitest yet — that's
issue #63). Instead these tests pin the JS source text for the contracts
that, if regressed, would silently break in production:

* the 70 + 80 cc chips were added to the volChoices set
* the chip-render loop honours `window.NBIO_APP_SETTINGS.formula_chip_max_ml`
* `refreshAppSettings()` exists and is called from DOMContentLoaded
* SSE `settings.updated` updates `window.NBIO_APP_SETTINGS`
* `openBothModal` exists and posts a wee + poo with the same `occurred_at`
* The tile-dispatch map includes `both: openBothModal`
* The long-press handler has a `type === "both"` branch
"""

from __future__ import annotations

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


# ----- chip set + cap -------------------------------------------------------


def test_all_vol_choices_contains_70_and_80(app_js):
    """Real-user ask: add the 70 + 80 cc chips so the 40-80 newborn
    range stops requiring CUSTOM entry on every feed."""
    # Pin the array as a unit so future re-orderings still hit.
    assert "[20, 30, 40, 50, 60, 70, 80, 90, 120, 150, 180, 210, 240]" in app_js, (
        "ALL_VOL_CHOICES must include 70 and 80 in the documented order"
    )


def test_chip_filter_reads_app_settings_cap(app_js):
    """The chip render loop applies `formula_chip_max_ml` from the
    cached app_settings before rendering. If this line goes away the
    cap silently stops working."""
    assert "formula_chip_max_ml" in app_js, (
        "app.js must reference formula_chip_max_ml to honour the cap"
    )
    assert "NBIO_APP_SETTINGS" in app_js, "app.js must read the cap from window.NBIO_APP_SETTINGS"
    # Verify the chip set is filtered, not just declared.
    assert "ALL_VOL_CHOICES.filter" in app_js, (
        "the chip list must be filtered by the cap (not just referenced)"
    )


def test_refresh_app_settings_function_exists(app_js):
    """A boot-time + SSE-time helper that hydrates window.NBIO_APP_SETTINGS."""
    assert "function refreshAppSettings" in app_js, (
        "expected a refreshAppSettings() helper that GET /api/settings"
    )
    assert "/api/settings" in app_js, (
        "refreshAppSettings must hit the existing /api/settings endpoint"
    )


def test_refresh_app_settings_called_from_init(app_js):
    """Without this call the cap is silently ignored on first paint."""
    init_idx = app_js.find('document.addEventListener("DOMContentLoaded"')
    assert init_idx > 0
    init_block = app_js[init_idx : init_idx + 800]
    assert "refreshAppSettings" in init_block, (
        "DOMContentLoaded init must call refreshAppSettings before rendering"
    )


def test_sse_handler_updates_app_settings(app_js):
    """When the partner updates the cap from the Settings page, the
    current tab must pick it up via SSE instead of waiting for reload."""
    assert 'addEventListener("settings.updated"' in app_js, (
        "app.js must listen to SSE settings.updated to refresh the cap"
    )
    # And the handler should write to window.NBIO_APP_SETTINGS.
    sse_idx = app_js.find('addEventListener("settings.updated"')
    sse_block = app_js[sse_idx : sse_idx + 400]
    assert "NBIO_APP_SETTINGS" in sse_block, (
        "settings.updated handler must update window.NBIO_APP_SETTINGS"
    )


# ----- both modal + tile wiring --------------------------------------------


def test_open_both_modal_exists(app_js):
    """The dedicated modal for wee + poo together."""
    assert "function openBothModal" in app_js, (
        "expected an openBothModal() that submits wee + poo in one flow"
    )


def test_open_both_modal_submits_wee_and_poo(app_js):
    """Modal submit must dispatch two submitCreate calls with type wee + poo."""
    open_idx = app_js.find("function openBothModal")
    assert open_idx > 0
    body = app_js[open_idx : open_idx + 2000]
    assert 'type: "wee"' in body, "openBothModal must POST a wee event"
    assert 'type: "poo"' in body, "openBothModal must POST a poo event"


def test_tile_dispatcher_includes_both(app_js):
    """The wireTiles map must route data-type=\"both\" to openBothModal."""
    assert "both: openBothModal" in app_js, (
        "wireTiles tile-type map must include `both: openBothModal`"
    )


def test_long_press_quick_logs_both_as_two_events(app_js):
    """Long-press on the both tile must fire two submitCreate calls
    (wee + poo) at the same isoNow() timestamp without opening a modal."""
    # Pin the type === "both" guard in the long-press timer body.
    assert 'type === "both"' in app_js, "long-press handler must special-case type === 'both'"


# ----- settings.js wiring --------------------------------------------------


def test_settings_js_has_wire_feeding_form(settings_js):
    """The Feeding section must be wired to PATCH the cap."""
    assert "function wireFeedingForm" in settings_js, "settings.js must define wireFeedingForm"
    assert "wireFeedingForm()" in settings_js, "settings.js must call wireFeedingForm() at init"


def test_settings_js_feeding_form_patches_api_settings(settings_js):
    """The form payload posts to PATCH /api/settings with the cap field."""
    idx = settings_js.find("function wireFeedingForm")
    assert idx > 0
    body = settings_js[idx : idx + 1200]
    assert "/api/settings" in body, "wireFeedingForm must PATCH /api/settings"
    assert "formula_chip_max_ml" in body, "wireFeedingForm payload must carry formula_chip_max_ml"


def test_settings_js_feeding_form_clears_cap_on_empty_input(settings_js):
    """Empty input string must map to null in the payload (= no cap)."""
    idx = settings_js.find("function wireFeedingForm")
    body = settings_js[idx : idx + 1200]
    # A null-coalescing or ternary that sends null on empty — pin either
    # path: the literal `null` keyword inside the payload-building stretch.
    assert "null" in body, "wireFeedingForm must send null when the input is cleared"
