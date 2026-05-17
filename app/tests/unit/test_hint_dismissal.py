"""
Source-level pins for the hint-dismissal namespace introduced with the
UX-hints PR (#11).

Each hint (sync-dot explainer, first-row hint, tile long-press caption)
records its dismissal in localStorage so it doesn't reappear on the
next page load. We pin:

1. The key namespace — `nbio.hint.<name>` — so it stays consistent
   with the existing `nbio.device_*` keys and lets the future
   settings UI clear them with one prefix filter.
2. The dismissal value — literal string `"dismissed"`. No JSON, no
   counter, no timestamp; aligns with how `nbio.device_color` is a
   bare string.
3. The absence of any shared "dismissed all hints" counter key —
   guards against drift toward a more complex model when the simple
   per-hint flag is sufficient.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[2] / "nbio" / "static" / "app.js"


def _src() -> str:
    return APP_JS.read_text()


EXPECTED_KEYS = {
    "nbio.hint.first_row",
    "nbio.hint.long_press",
    "nbio.hint.sync_dot",
}


def test_hint_keys_use_nbio_hint_prefix():
    """Every hint key in app.js sits under the `nbio.hint.<name>` namespace."""
    src = _src()
    # Find every "nbio.hint.<word>" literal.
    found = set(re.findall(r'"(nbio\.hint\.[a-z_]+)"', src))
    missing = EXPECTED_KEYS - found
    assert not missing, (
        f"app.js is missing hint-key literals: {missing}. "
        f"Found: {found}"
    )
    # Reject stray keys outside the expected set so the future settings
    # UI can prefix-filter without surprises.
    extras = found - EXPECTED_KEYS
    assert not extras, (
        f"app.js declares unexpected hint keys: {extras}. "
        f"If you're adding a new hint, update EXPECTED_KEYS in this test."
    )


def test_hint_dismiss_value_is_literal_dismissed():
    """
    The value written/read for a dismissed hint is the literal string
    `"dismissed"` (no JSON, no number). Tests grep for the value
    appearing near a `localStorage.setItem` or comparison.
    """
    src = _src()
    # Match `setItem("nbio.hint.something", "dismissed")` OR
    # `=== "dismissed"` near a hint-key read.
    has_set = re.search(
        r'setItem\(\s*"nbio\.hint\.[a-z_]+"\s*,\s*"dismissed"\s*\)',
        src,
    )
    has_set_via_var = re.search(
        r'setItem\([^,]+,\s*"dismissed"\s*\)',
        src,
    )
    has_comparison = '=== "dismissed"' in src
    assert (has_set or has_set_via_var) and has_comparison, (
        "expected `localStorage.setItem(<key>, \"dismissed\")` AND "
        '`=== "dismissed"` comparison in app.js'
    )


def test_no_orphan_hint_counter():
    """
    Negative pin: there must NOT be a `nbio.hint.count` or
    `nbio.hint.session` shared key. The per-hint flag model is the
    deliberate choice.
    """
    src = _src()
    assert "nbio.hint.count" not in src, (
        "drift detected: a shared hint counter key was introduced. The "
        "design uses per-hint dismissal flags only."
    )
    assert "nbio.hint.session" not in src, (
        "drift detected: a session-counter hint key was introduced."
    )
