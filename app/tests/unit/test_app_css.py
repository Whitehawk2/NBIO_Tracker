"""
Source-level pins on `nbio/static/app.css` for the UX-hints PR (#11).

These tests read the CSS as text rather than parsing it — the suite
doesn't carry a CSS-parsing harness today and the contracts we want to
protect are small, stable, and grep-able.

Pin reasons:
- The `:focus-visible` rule unblocks keyboard navigation; it's small
  enough that a regression in formatting could easily drop the
  selectors. We pin presence of the selector list AND that it targets
  buttons, tiles, and event rows.
- The dark-mode `--text-muted` value is borderline WCAG-AA on
  `--bg-elev` at the previous `#8a8a93`. We pin the bumped value so a
  future palette refactor doesn't silently regress contrast.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_CSS = Path(__file__).resolve().parents[2] / "nbio" / "static" / "app.css"


def _src() -> str:
    return APP_CSS.read_text()


def test_focus_visible_rule_present():
    """A global `:focus-visible` outline must be declared."""
    src = _src()
    # The rule body declares an outline AND outline-offset using the
    # brand --accent token. We match the full block loosely so spacing
    # tweaks don't break the test.
    assert ":focus-visible" in src, "expected a :focus-visible rule in app.css"
    m = re.search(
        r":focus-visible\s*\{[^}]*outline\s*:\s*2px\s+solid\s+var\(--accent\)[^}]*"
        r"outline-offset\s*:\s*2px[^}]*\}",
        src,
        flags=re.DOTALL,
    )
    assert m, (
        "expected `:focus-visible { outline: 2px solid var(--accent); "
        "outline-offset: 2px }` rule in app.css"
    )


def test_focus_visible_covers_tiles_and_rows():
    """
    Tab navigation must surface the focused tile or event row — not just
    buttons / inputs / links. Pin that `.tile` and `.event-row` are in
    the global focus-visible selector list (a rule that lists both
    among its selectors).
    """
    src = _src()
    # Find every `:focus-visible` rule and look for one whose selector
    # list contains both `.tile:focus-visible` and `.event-row:focus-visible`.
    # Component-specific rules (e.g. `.row-menu:focus-visible`) match a
    # single selector and don't cover the contract.
    matched = False
    for m in re.finditer(r"([^{}]*?:focus-visible[^{}]*?)\{", src):
        selectors = m.group(1)
        if ".tile:focus-visible" in selectors and ".event-row:focus-visible" in selectors:
            matched = True
            break
    assert matched, (
        "expected a :focus-visible rule listing both `.tile` and "
        "`.event-row` so keyboard focus is visible on both clickable "
        "but non-native-button elements"
    )


def test_row_menu_styled():
    """A `.row-menu` rule must exist styling the trailing-edge button."""
    src = _src()
    assert re.search(r"\.row-menu\s*\{", src), "expected a `.row-menu { ... }` rule in app.css"


def test_tile_hint_styled():
    """A `.tile-hint` rule must exist styling the long-press caption."""
    src = _src()
    # The selector list might group .tile-hint with .first-row-hint; accept either.
    assert re.search(r"\.tile-hint\s*[,{]", src), "expected a `.tile-hint` selector in app.css"


def test_hint_dismiss_button_styled():
    """The `.hint-dismiss` × button must have its own styling."""
    src = _src()
    assert re.search(r"\.hint-dismiss\s*\{", src), (
        "expected a `.hint-dismiss { ... }` rule in app.css"
    )


def test_no_recent_class_styled_distinctly():
    """
    `.no-recent` (the tile empty-state placeholder) must be visually
    distinct from `.muted` so users can't confuse it with real
    metadata. We pin: a `.no-recent` rule exists, AND its body differs
    from a bare `color: var(--text-muted)` (must add at least font-style
    or a stronger colour).
    """
    src = _src()
    m = re.search(r"\.no-recent\s*\{([^}]+)\}", src, flags=re.DOTALL)
    assert m, "expected a `.no-recent { ... }` rule in app.css"
    body = m.group(1)
    # Must have some visual differentiation beyond bare muted colour.
    has_italic = "font-style" in body and "italic" in body
    has_stronger_color = "color-mix" in body or "opacity" in body
    assert has_italic or has_stronger_color, (
        ".no-recent must add italic OR a stronger colour-mix/opacity so "
        f"it's distinct from `.muted`; got body={body!r}"
    )


def test_sync_dot_btn_neutralises_default_button_appearance():
    """
    Without `appearance: none`, Android Chrome renders a bare <button>
    with its UA default `ButtonFace` background — a light-grey
    rectangle that's especially jarring in dark mode. The sync-dot
    button must explicitly neutralise that.

    Pinned because the v1.0.1 → v1.1.0 production regression had a
    visible white rectangle in the header where the sync dot lived;
    root cause was the missing `appearance: none` on `.sync-dot-btn`.
    """
    src = _src()
    m = re.search(r"\.sync-dot-btn\s*\{([^}]+)\}", src, flags=re.DOTALL)
    assert m, "expected a `.sync-dot-btn { ... }` rule in app.css"
    body = m.group(1)
    # `appearance: none` (the shorthand) covers webkit too on Chrome 84+,
    # but we want both forms to be defensive across browsers.
    assert re.search(r"\bappearance\s*:\s*none", body), (
        "`.sync-dot-btn` must declare `appearance: none` to neutralise "
        "the Chrome UA <button> default ButtonFace background"
    )


def test_tile_hint_background_uses_solid_color():
    """
    `.tile-hint` / `.first-row-hint` previously used
    `color-mix(in srgb, var(--bg-sunk) 70%, transparent)` for the
    background — fine on Chrome 111+, but any cascade or specificity
    miss falls through to "no background" → renders white. Solid
    `var(--bg-sunk)` is one less thing that can fail open.

    Only the `background:` declaration's value is inspected (comments
    in the rule body are allowed to mention color-mix for context).
    """
    src = _src()
    m = re.search(r"\.tile-hint[^{]*\{([^}]+)\}", src, flags=re.DOTALL)
    assert m, "expected a `.tile-hint` rule in app.css"
    body = m.group(1)
    # Strip CSS comments before inspecting declarations.
    body_no_comments = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    bg = re.search(r"\bbackground\s*:\s*([^;]+);", body_no_comments)
    assert bg, "`.tile-hint` rule must declare a `background:`"
    bg_value = bg.group(1).strip()
    assert "color-mix" not in bg_value, (
        f"`.tile-hint` background must NOT use color-mix(... transparent); "
        f"got {bg_value!r}. Use a solid `var(--bg-sunk)` / `var(--bg-elev)` so "
        f"any cascade failure doesn't fall through to a white background."
    )
    assert "var(--" in bg_value, (
        f".tile-hint background must use a CSS variable; got {bg_value!r}"
    )


def test_dark_mode_text_muted_bumped():
    """
    `html.dark` `--text-muted` must be the bumped contrast value
    (~#a0a0a8). The previous `#8a8a93` was borderline AA on `--bg-elev`.
    """
    src = _src()
    # Grab the html.dark block.
    m = re.search(r"html\.dark\s*\{([^}]+)\}", src, flags=re.DOTALL)
    assert m, "html.dark token block not found in app.css"
    block = m.group(1)
    muted = re.search(r"--text-muted\s*:\s*([#a-zA-Z0-9]+)\s*;", block)
    assert muted, "html.dark must declare --text-muted"
    value = muted.group(1).lower()
    assert value != "#8a8a93", (
        "dark-mode --text-muted must be bumped from the borderline-AA value #8a8a93"
    )
    # Allow a small window: the colour should be visibly lighter than
    # #8a8a93 (so each channel ~>= 0x95).
    assert re.match(r"#[9-f][0-9a-f]{5}$", value), (
        f"dark-mode --text-muted should be >= #909090-ish for AA on --bg-elev; got {value}"
    )
