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
    that a `wireSyncDot` function exists and wires a click listener to
    the `[data-sync-explain]` element.
    """
    src = _src()
    assert "data-sync-explain" in src, "expected `data-sync-explain` to be referenced in app.js"
    idx = src.find("function wireSyncDot")
    assert idx >= 0, "expected a `wireSyncDot()` function in app.js"
    # The function body is short — look at the next ~400 chars.
    block = src[idx : idx + 400]
    assert "data-sync-explain" in block, "wireSyncDot must select the [data-sync-explain] element"
    assert 'addEventListener("click"' in block or "addEventListener('click'" in block, (
        "wireSyncDot must wire a click listener on the sync-explain element"
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
        "setSyncState must mutate aria-label / title so the state is accessible, not just visual"
    )


def test_row_html_includes_row_menu():
    """
    Client-side `rowHTML(ev)` must mirror the server template by
    emitting the `.row-menu` button. Otherwise rows inserted via
    SSE/optimistic paths would silently lack the affordance.
    """
    src = _src()
    idx = src.find("function rowHTML(")
    assert idx >= 0
    block = src[idx : idx + 1500]
    assert "row-menu" in block, (
        "rowHTML must emit the `.row-menu` button so SSE-/optimistic-"
        "inserted rows match the server template"
    )
    assert "data-row-menu" in block


def test_row_menu_click_stops_propagation():
    """
    Clicking the `⋯` button must NOT bubble to the row's tap-to-edit
    click handler. Pinned by looking for `stopPropagation()` near the
    row-menu wiring.
    """
    src = _src()
    # Find the wireRowMenu function (or wherever row-menu click is bound).
    idx = src.find("function wireRowMenu")
    assert idx >= 0, "expected a `wireRowMenu()` function in app.js"
    block = src[idx : idx + 600]
    assert "stopPropagation" in block, (
        "wireRowMenu must call event.stopPropagation() so clicks on the "
        "menu button don't bubble to the row tap-to-edit handler"
    )


def test_row_menu_opens_action_sheet_with_edit_and_delete():
    """
    The action sheet opened by the row-menu must offer Edit and Delete
    actions. Pin the literal strings near `openRowActionSheet`.
    """
    src = _src()
    idx = src.find("function openRowActionSheet")
    assert idx >= 0, "expected an `openRowActionSheet()` function in app.js"
    block = src[idx : idx + 1000]
    assert "Edit" in block, "action sheet must offer an Edit button"
    assert "Delete" in block, "action sheet must offer a Delete button"


def test_row_swipe_skips_when_target_in_row_menu():
    """
    The row's `touchstart` / `touchmove` handlers must early-return
    when the touch starts inside a `.row-menu` button — otherwise the
    button can never be tapped on touch devices because the row eats
    the gesture.
    """
    src = _src()
    idx = src.find("function attachRowGestures")
    assert idx >= 0
    block = src[idx : idx + 1200]
    assert "closest" in block and "row-menu" in block, (
        "attachRowGestures must check `e.target.closest('.row-menu')` to "
        "skip the swipe gesture when touching the menu button"
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
    assert "ev.notes" in block, "the notes-icon emission in rowHTML must be conditional on ev.notes"


def test_timeline_marks_wired_for_tap_to_show_detail():
    """
    On Android Chrome the SVG `<title>` element only renders on hover
    (which touch devices don't have). User: 'feedings on reports
    timeline still not clickable, no way to know per-feeding cc amount.'

    Fix: a `wireTimelineMarks()` function binds click handlers to each
    `.timeline .mark` rect. On click it reads the `<title>` text and
    surfaces it via the existing toast.
    """
    src = _src()
    assert "function wireTimelineMarks" in src, (
        "expected a `wireTimelineMarks()` function in app.js so timeline "
        "marks are tappable on touch devices"
    )
    idx = src.find("function wireTimelineMarks")
    block = src[idx : idx + 600]
    assert ".timeline .mark" in block or "timeline .mark" in block, (
        "wireTimelineMarks must target `.timeline .mark` rects"
    )
    assert "showToast" in block, (
        "wireTimelineMarks must call showToast() with the mark's title text"
    )


def test_sse_deleted_handler_suppresses_own_echo():
    """
    Critical reactive-refresh bug: `doSoftDelete` calls
    `bumpOverviews(deleted, -1)` immediately, then the SSE
    `event.deleted` echo arrives ~50ms later while the row is still
    in the DOM (250ms `removing` animation). The SSE handler then
    bumps AGAIN, double-decrementing the cc total. With clamp at 0,
    a 245→0 jump is what the user reported.

    Fix mirrors the existing own-echo pattern for `created`: track
    own deletes in `ownDeletes` and skip the SSE bump when matched.
    """
    src = _src()
    # An ownDeletes container exists.
    assert "ownDeletes" in src, (
        "expected an `ownDeletes` Set/Map matching the ownIdems pattern for created events"
    )
    # The SSE deleted handler checks it before bumping.
    idx = src.find('kind === "deleted"')
    assert idx >= 0
    block = src[idx : idx + 600]
    assert "ownDeletes" in block, (
        "SSE event.deleted handler must check ownDeletes before bumping — "
        "otherwise the user's own delete double-decrements the cc total"
    )


def test_wire_existing_rows_hydrates_formula_volume_ml():
    """
    Second half of the reactive-refresh regression: when the user
    DELETES a server-rendered formula row, `doSoftDelete` reads
    `row.__event` and passes it to `bumpOverviews`. `wireExistingRows`
    sets up `__event` from DOM data — but pre-fix it only stored id,
    type, occurred_at, and notes. With no `formula_volume_ml`, the
    formula branch in `bumpOverviews` skipped and the cc total stayed
    stale until reload.
    """
    src = _src()
    idx = src.find("function wireExistingRows")
    assert idx >= 0, "wireExistingRows function not found"
    block = src[idx : idx + 800]
    assert "formula_volume_ml" in block, (
        "wireExistingRows must hydrate `formula_volume_ml` into `row.__event` "
        "so deletions of server-rendered formula rows bump the cc total"
    )


def test_optimistic_dict_includes_formula_fields():
    """
    Critical regression: `submitCreate`'s optimistic event-row dict
    copies feed_side / feed_duration_min / poo_quality / notes from the
    payload, but pre-fix it forgot `formula_brand` and
    `formula_volume_ml`. The result: `bumpOverviews(optimistic, +1)`'s
    formula branch checked `ev.formula_volume_ml` and silently fell
    through because the field was undefined. The today-card cc total
    and the last-3-days cc cell didn't refresh on a POST — only on a
    page reload (when the server-rendered HTML had the values).

    Pin the two fields explicitly so the regression can't return.
    """
    src = _src()
    idx = src.find("const optimistic = {")
    assert idx >= 0, "optimistic dict not found in app.js"
    # Look at the full literal block (~30 lines after).
    block = src[idx : idx + 800]
    assert "formula_brand:" in block, (
        "submitCreate's optimistic dict must include `formula_brand:` so "
        "the optimistic row + bumpOverviews receive the brand"
    )
    assert "formula_volume_ml:" in block, (
        "submitCreate's optimistic dict must include `formula_volume_ml:` "
        "so bumpOverviews' formula branch can sum the cc total"
    )


def test_bump_overviews_bumps_formula_ml_for_formula_events():
    """
    `bumpOverviews` must bump the `formula_ml` cell by the event's
    `formula_volume_ml` (signed by delta) when a formula event lands.
    Otherwise the home and last-3-days cc totals fall out of sync with
    the server after an optimistic POST or SSE delivery.
    """
    src = _src()
    idx = src.find("function bumpOverviews(")
    assert idx >= 0, "bumpOverviews() function not found in app.js"
    block = src[idx : idx + 3000]
    assert 'ev.type === "formula"' in block, (
        "bumpOverviews must branch on ev.type === 'formula' to handle the cc total"
    )
    assert "ev.formula_volume_ml" in block, (
        "bumpOverviews must read ev.formula_volume_ml to scale the bump"
    )
    assert 'data-count="formula_ml"' in block, (
        'bumpOverviews must target the today-card `[data-count="formula_ml"]` cell'
    )
    assert 'data-col="formula_ml"' in block, (
        'bumpOverviews must target the last-3-days `[data-col="formula_ml"]` cell'
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


def test_app_js_has_wire_vitd_banner():
    """
    `wireVitDBanner` must exist and bind the `[data-vitd-give]` button to
    an optimistic POST flow against the events endpoint. Without this the
    banner's "Give now" button is a no-op (the entire #8.5 flow falls back
    to manual tile-tap log).
    """
    src = _src()
    assert "function wireVitDBanner(" in src, (
        "expected `wireVitDBanner()` function in app.js — drives the #8.5 banner"
    )
    idx = src.find("function wireVitDBanner(")
    block = src[idx : idx + 2500]
    assert "[data-vitd-give]" in block, (
        "wireVitDBanner must look up the Give-now button via `[data-vitd-give]`"
    )
    assert '"vitd"' in block, "wireVitDBanner must POST `type: 'vitd'` events"
    # Wired into init so the listener fires on first paint.
    assert "wireVitDBanner();" in src, (
        "wireVitDBanner() must be called from the DOMContentLoaded init block"
    )


def test_app_js_bump_overviews_handles_vitd():
    """
    `bumpOverviews` must branch on `ev.type === "vitd"` and route to the
    banner renderer. Otherwise the vit D banner doesn't refresh until the
    page is reloaded — same regression class as the formula_ml strip.
    """
    src = _src()
    idx = src.find("function bumpOverviews(")
    assert idx >= 0, "bumpOverviews() function not found in app.js"
    block = src[idx : idx + 3000]
    assert 'ev?.type === "vitd"' in block or 'ev.type === "vitd"' in block, (
        "bumpOverviews must branch on `ev.type === 'vitd'` for the banner path"
    )
    assert "renderVitdBanner(" in block, (
        "bumpOverviews's vitd branch must call `renderVitdBanner(ev, delta)`"
    )


def test_row_html_vitd_emoji():
    """The event row's emoji map must include 💊 for type='vitd'."""
    src = _src()
    # Find rowHTML and check the emoji chain handles "vitd".
    idx = src.find("function rowHTML(")
    assert idx >= 0, "rowHTML() function not found in app.js"
    block = src[idx : idx + 2000]
    assert 'ev.type === "vitd"' in block, (
        "rowHTML must branch on `ev.type === 'vitd'` for the 💊 emoji"
    )
    assert "💊" in block, "rowHTML must emit the 💊 emoji for vit D events"


def test_refresh_vitd_late_class_exists():
    """
    `refreshVitdLateClass` keeps the after-18:00 nudge fresh on long-lived
    PWA tabs (hourly setInterval). Without it the banner stays in its
    not-yet-overdue state past the threshold.
    """
    src = _src()
    assert "function refreshVitdLateClass(" in src, (
        "expected `refreshVitdLateClass()` function in app.js for the 18:00 nudge"
    )
    idx = src.find("function refreshVitdLateClass(")
    block = src[idx : idx + 600]
    assert "getHours()" in block, (
        "refreshVitdLateClass must read the local hour via `new Date().getHours()`"
    )
    assert "is-late" in block, "refreshVitdLateClass must toggle the `.is-late` class on the banner"
    # Hourly heartbeat so it triggers on long-running PWA tabs.
    assert "setInterval(refreshVitdLateClass" in src, (
        "refreshVitdLateClass must be scheduled via setInterval in the init block"
    )


def test_open_edit_for_dispatches_vitd_to_its_own_modal():
    """
    Tapping a vit D event row must NOT fall through to `openPooModal` —
    the user-reported bug was the edit affordance opening the poo modal
    (with stool quality chips and a 'Save Poo' button) for vit D events.
    `openEditFor` must dispatch `type === "vitd"` to its own modal.
    """
    src = _src()
    idx = src.find("async function openEditFor(")
    assert idx >= 0, "openEditFor() function not found in app.js"
    block = src[idx : idx + 1500]
    assert 'full.type === "vitd"' in block, (
        "openEditFor must branch on `full.type === 'vitd'` so vit D rows don't "
        "open the poo modal (production bug: tapping a vit D row showed the poo "
        "quality chips + 'Save Poo' button)"
    )
    assert "openVitdModal(" in block, (
        "openEditFor's vitd branch must dispatch to `openVitdModal(prefill)`"
    )


def test_open_vitd_modal_uses_time_and_notes_only():
    """
    Vit D events only carry `occurred_at` + optional `notes` (no side,
    no duration, no quality, no volume). The modal must reflect that —
    just a time-chip picker + a notes input + a submit button. Pinning
    these so a future regression doesn't, say, accidentally show poo
    quality chips.
    """
    src = _src()
    idx = src.find("function openVitdModal(")
    assert idx >= 0, "openVitdModal() function not found in app.js"
    block = src[idx : idx + 1500]
    # Must build the time-chip picker like the other modals.
    assert "buildTimeChips(" in block, (
        "openVitdModal must call buildTimeChips for the retro-time picker"
    )
    # Submits with `type: 'vitd'` (so the back-end stores the right type).
    assert '"vitd"' in block, "openVitdModal must POST events with `type: 'vitd'`"
    # The modal title must surface the 💊 affordance.
    assert "💊" in block, "openVitdModal title must include the 💊 emoji"
    # MUST NOT contain poo-quality wiring (the bug we're fixing).
    assert "poo_quality" not in block, (
        "openVitdModal must NOT carry poo_quality — that's how the buggy "
        "fall-through to openPooModal showed up. Keep it minimal: time + notes."
    )
