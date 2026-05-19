"""
Source-level pins for `settings.js` and the related bootstrap + age
refresh wiring (#6). No jsdom — we read the JS as text, the same
approach used by test_tile_gestures.py.

Pin contracts:
- Theme picker writes BOTH localStorage AND document.documentElement.dataset.theme.
- Baby + device form submits use PATCH/PUT to the right endpoints.
- Server-info section fetches /api/server-info and populates the <dl>.
- base.html's pre-paint bootstrap reads localStorage.getItem('nbio.theme').
- app.js refreshes `[data-baby-age]` periodically so the displayed
  age doesn't go stale during long sessions.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_JS = ROOT / "nbio" / "static" / "settings.js"
APP_JS = ROOT / "nbio" / "static" / "app.js"
BASE_HTML = ROOT / "nbio" / "templates" / "base.html"


def _settings_src() -> str:
    return SETTINGS_JS.read_text()


def _app_src() -> str:
    return APP_JS.read_text()


def _base_src() -> str:
    return BASE_HTML.read_text()


def test_settings_js_has_wire_theme_picker():
    src = _settings_src()
    assert "function wireThemePicker" in src, "missing wireThemePicker()"
    idx = src.find("function wireThemePicker")
    block = src[idx : idx + 1000]
    assert "localStorage" in block, "wireThemePicker must persist to localStorage"
    assert "nbio.theme" in block, "wireThemePicker must use the `nbio.theme` localStorage key"
    assert "dataset.theme" in block or "data-theme" in block, (
        "wireThemePicker must update document.documentElement.dataset.theme"
    )


def test_settings_js_baby_form_uses_patch_babies():
    src = _settings_src()
    assert "/api/babies" in src, "settings.js must POST/PATCH to /api/babies"
    # Method is PATCH — either as `method: 'PATCH'` literal OR passed as
    # an argument to a helper (e.g. `submitJson('/api/babies', 'PATCH', ...)`).
    idx = src.find("/api/babies")
    block = src[max(0, idx - 80) : idx + 80]
    assert '"PATCH"' in block or "'PATCH'" in block, (
        "baby form must use PATCH (literal in the same call as /api/babies)"
    )


def test_settings_js_device_form_uses_put_devices():
    src = _settings_src()
    assert "/api/devices/" in src, "settings.js must call /api/devices/{id}"
    idx = src.find("/api/devices/")
    block = src[max(0, idx - 80) : idx + 200]
    assert '"PUT"' in block or "'PUT'" in block, (
        "device form must use PUT (literal in the same call as /api/devices/)"
    )


def test_settings_js_server_info_fetches_api():
    src = _settings_src()
    assert "function wireServerInfo" in src
    idx = src.find("function wireServerInfo")
    block = src[idx : idx + 800]
    assert "/api/server-info" in block, "wireServerInfo must GET /api/server-info"


def test_settings_js_sends_x_device_id_header():
    """
    Future-auth seam: settings.js must send `X-Device-Id` on every
    write so `current_actor` resolves to a device-kind Actor (today
    unused inside route bodies, but the contract is in place).
    """
    src = _settings_src()
    assert "X-Device-Id" in src, (
        "settings.js writes must send X-Device-Id header (future-auth seam)"
    )


def test_settings_js_tabs_polyfill_present():
    """
    Older browsers without native `<details name=...>` exclusive
    accordion get a small polyfill that closes siblings on toggle.
    """
    src = _settings_src()
    assert "function wireSettingsTabs" in src, "missing wireSettingsTabs()"


def test_base_html_bootstrap_reads_localstorage_theme():
    """
    base.html's pre-paint bootstrap script reads `nbio.theme` from
    localStorage and sets `dataset.theme` BEFORE the stylesheet
    applies. Without this, a cold-load shows a flash of the default
    theme.
    """
    src = _base_src()
    assert "nbio.theme" in src, "base.html bootstrap must read localStorage.nbio.theme"
    assert "dataset.theme" in src, "base.html bootstrap must set dataset.theme pre-paint"


def test_app_js_refreshes_baby_age():
    """
    `[data-baby-age]` is server-rendered correctly on page load but
    long sessions (e.g. PWA left open overnight) need a periodic
    refresh so '12d' doesn't read '12d' the next morning.
    """
    src = _app_src()
    assert "data-baby-age" in src, "app.js must reference data-baby-age to refresh the header"


def test_settings_js_has_wire_weight_form():
    """Weight subsection (v1.1.1) — modal-launching wiring."""
    src = _settings_src()
    assert "function wireWeightForm" in src, "missing wireWeightForm() in settings.js"
    assert "openWeightModal" in src, (
        "wireWeightForm must dispatch the Update button to openWeightModal"
    )
    # POSTs to /api/growth.
    assert "/api/growth" in src, "weight modal must POST to /api/growth"
    # Wired in DOMContentLoaded.
    assert "wireWeightForm();" in src, "wireWeightForm must be called from init"
