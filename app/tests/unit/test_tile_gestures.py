"""
Source-level pins for the home-page tile gesture hardening — production
finding follow-up: scrolling the page would sometimes silently log an
event because the tile long-press timer fired before the browser issued
touchcancel.

Two contracts we don't want to silently regress:

1. Long-press timer is `LONG_PRESS_MS = 3000` (was 600ms — too easy to
   trip on scroll).
2. The wire-tiles handler attaches `touchmove` / `mousemove` listeners
   AND cancels the timer when the pointer moves beyond the threshold.

We pin these by reading app.js as text rather than running it under a
browser — the project doesn't carry a Playwright/jsdom harness today.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[2] / "nbio" / "static" / "app.js"


def _src() -> str:
    return APP_JS.read_text()


def test_tile_long_press_uses_3_second_timer():
    """3000ms hold required for the silent quick-log."""
    src = _src()
    # Look for `LONG_PRESS_MS = <N>` and `setTimeout(..., LONG_PRESS_MS)`
    m = re.search(r"LONG_PRESS_MS\s*=\s*(\d+)", src)
    assert m, "expected `LONG_PRESS_MS = N` constant in app.js"
    assert int(m.group(1)) == 3000, f"long-press timer must be 3 seconds; found {m.group(1)}ms"
    # Make sure the constant actually drives setTimeout, not just sits unused.
    # The setTimeout call spans multiple lines so we just look for the closing
    # `, LONG_PRESS_MS)` token that follows the inline callback.
    assert ", LONG_PRESS_MS)" in src, (
        "LONG_PRESS_MS must be the timeout argument to setTimeout in tile wiring"
    )


def test_tile_wiring_attaches_touchmove_handler():
    """
    touchmove + mousemove listeners must be attached so finger drift
    cancels the long-press. Without these, scrolling on a tile would
    silently log an event.
    """
    src = _src()
    assert 'addEventListener("touchmove"' in src, (
        "wireTiles must register a touchmove listener so scrolling cancels long-press"
    )
    assert 'addEventListener("mousemove"' in src, (
        "wireTiles must register a mousemove listener for the desktop/mouse path"
    )


def test_tile_wiring_declares_move_threshold():
    """A move-threshold constant must be present (the cancellation gate)."""
    src = _src()
    m = re.search(r"MOVE_THRESHOLD\s*=\s*(\d+)", src)
    assert m, "expected `MOVE_THRESHOLD = N` constant in app.js"
    threshold = int(m.group(1))
    # Reasonable bounds: too small triggers on natural finger tremor; too
    # large doesn't actually cancel on a scroll gesture.
    assert 3 <= threshold <= 30, f"MOVE_THRESHOLD looks off: {threshold}"


def test_click_handler_suppresses_after_drag():
    """
    After a scroll/drag, the click event must NOT open the modal. The
    handler checks `movedDuringTouch` (or longFired) and returns early.
    """
    src = _src()
    # Look for the click handler block on a tile
    idx = src.find('addEventListener("click"', src.find("function wireTiles"))
    assert idx >= 0, "click handler in wireTiles not found"
    snippet = src[idx : idx + 400]
    assert "movedDuringTouch" in snippet, (
        "click handler must check movedDuringTouch so scrolling doesn't open the modal"
    )


def test_app_js_has_hint_dismissed_helper():
    """
    The hint-dismissal API is centralised so each hint follows the same
    pattern. Pin that `hintDismissed` and `dismissHint` helpers exist
    and use `localStorage`.
    """
    src = _src()
    assert "function hintDismissed" in src, "missing hintDismissed() helper"
    assert "function dismissHint" in src, "missing dismissHint() helper"
    # Helpers must touch localStorage.
    idx = src.find("function hintDismissed")
    block = src[idx : idx + 400]
    assert "localStorage" in block, "hintDismissed must read localStorage"


def test_sync_dot_click_handler_attached():
    """
    Tapping the header sync dot must open an explainer popover. Pin
    that a click handler is wired to the `[data-sync-explain]` element.
    """
    src = _src()
    # Click handler can be wired by querySelector or delegation; both
    # mention the data attribute.
    assert "data-sync-explain" in src, (
        "expected `data-sync-explain` to be referenced in app.js so the "
        "sync-badge button has a click handler"
    )
    # Look for an addEventListener on click anywhere within 800 chars of
    # the data-sync-explain reference.
    idx = src.find("data-sync-explain")
    window = src[max(0, idx - 400) : idx + 800]
    assert 'addEventListener("click"' in window or 'addEventListener(\'click\'' in window, (
        "expected a click listener wired near data-sync-explain"
    )


def test_set_sync_state_updates_aria_label():
    """
    The sync-dot button's aria-label / title must change with state so
    screen-reader users hear "Connection: live" vs "Connection: offline"
    — not just the static title="Connection".
    """
    src = _src()
    idx = src.find("function setSyncState(")
    assert idx >= 0, "setSyncState() function not found"
    block = src[idx : idx + 600]
    assert "aria-label" in block or "ariaLabel" in block or "setAttribute" in block, (
        "setSyncState must mutate aria-label / title so the state is "
        "accessible, not just visual"
    )


def test_row_html_includes_notes_icon_branch():
    """
    The client-side `rowHTML(ev)` must mirror the server template by
    conditionally rendering the 📝 notes-exists icon. Tested at the
    source level — the rendered row markup must contain a branch that
    checks `ev.notes` and emits `ev-notes-icon`.
    """
    src = _src()
    idx = src.find("function rowHTML(")
    assert idx >= 0, "rowHTML function not found in app.js"
    block = src[idx : idx + 1200]
    assert "ev-notes-icon" in block, (
        "rowHTML must render an `ev-notes-icon` element so client-inserted "
        "rows match the server template"
    )
    assert "ev.notes" in block, (
        "the notes-icon emission in rowHTML must be conditional on ev.notes"
    )


def test_formula_volume_picker_uses_only_segmented_wrap():
    """
    Volume picker chips overflow horizontally when both .segmented and
    .segmented-wrap are applied — the former forces grid-auto-flow:column.
    The picker must use ONLY `segmented-wrap`.
    """
    src = _src()
    # Find the volSeg declaration line
    m = re.search(r"volSeg\.className\s*=\s*\"([^\"]+)\"", src)
    assert m, "expected `volSeg.className = '…'` in app.js"
    classes = set(m.group(1).split())
    assert "segmented-wrap" in classes, "volSeg must include the wrap class"
    assert "segmented" not in classes, (
        "volSeg must NOT include `.segmented` — its grid-auto-flow:column"
        " prevents the chips from wrapping. Use only `.segmented-wrap`."
    )
