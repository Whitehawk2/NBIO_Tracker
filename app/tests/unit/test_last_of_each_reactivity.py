"""
Source-level pins for the G4 "last feed/wee/poo" today-card reactivity (PR-B4).

The today-card `[data-last=...]` cells show the all-time most-recent non-deleted
event per lane. They are made reactive by registering a THIRD updater
(`lastOfEachUpdater`) into the applyEvent dispatch seam — so every event path
(optimistic create, SSE, edit, undelete) drives them with no call-site changes.

These pins guard the load-bearing structural decisions the design review fixed,
which a browser/e2e run can't cheaply assert per-commit:
  - the updater is actually REGISTERED into the seam (else it never runs),
  - it is UPSERT-ONLY (delete-recompute deferred to #93's store, since the
    all-time previous event can be older than the event-list's ~2-day window),
  - the cell suffix is injected as TEXT, never innerHTML (the escaping/XSS guard:
    notes/free-text must not become markup),
  - the pure helpers are exported on the seam (NBIO_APPLY) so they're unit-tested.
We read the sources as text; the runtime behaviour itself is covered by the e2e
spec `reactivity-last-of-each.spec.js` and the Vitest units in apply-event.test.js.
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "nbio" / "static"
APP_JS = STATIC / "app.js"
APPLY_JS = STATIC / "apply-event.js"


def _fn_body(src: str, signature: str) -> str:
    """A JS function body from its signature to the first 2-space-indented close."""
    idx = src.find(signature)
    assert idx >= 0, f"{signature!r} not found"
    end = src.find("\n  }", idx)
    return src[idx : end if end > idx else idx + 2000]


def test_updater_is_registered_into_the_seam() -> None:
    src = APP_JS.read_text()
    assert "APPLY.registerUpdater(lastOfEachUpdater)" in src, (
        "lastOfEachUpdater must be registered into the applyEvent seam, or the "
        "last-of-each cells never update."
    )


def test_updater_targets_the_data_last_cells_via_pure_helpers() -> None:
    body = _fn_body(APP_JS.read_text(), "function lastOfEachUpdater(")
    assert "APPLY.laneForType(" in body, "must derive the lane from the event type"
    assert "APPLY.lastCellWins(" in body, "must gate the render on recency"
    assert '[data-last="' in body, "must target the today-card last-of-each cells"


def test_updater_is_upsert_only_delete_deferred() -> None:
    body = _fn_body(APP_JS.read_text(), "function lastOfEachUpdater(")
    # Upsert-only: bail on any non-upsert action (delete-recompute is #93's store).
    assert "rowAction(" in body and '"upsert"' in body, (
        "lastOfEachUpdater must be upsert-only (guard on rowAction === 'upsert'); "
        "delete-recompute of the displayed-last is deferred to #93."
    )


def test_cell_suffix_is_injected_as_text_not_innerhtml() -> None:
    body = _fn_body(APP_JS.read_text(), "function renderLastCell(")
    assert "lastSuffix(" in body, "renderLastCell builds the cell's detail suffix"
    assert "createTextNode(" in body, (
        "the free-text suffix must be injected as a text node (escaping guard)"
    )
    # Forbid the actual `.innerHTML` sink (dot-prefixed), not the bare word — a
    # WHY-comment may legitimately mention innerHTML in prose.
    assert ".innerHTML" not in body, (
        "renderLastCell must not use .innerHTML — free-text notes would become markup "
        "(XSS). Build the cell with createElement/textContent/createTextNode."
    )


def test_pure_helpers_exported_on_the_seam() -> None:
    src = APPLY_JS.read_text()
    for name in ("laneForType", "lastCellWins", "lastSuffix"):
        assert f"function {name}(" in src, f"{name} must be defined in apply-event.js"
        assert name in src.split("window.NBIO_APPLY = {", 1)[1], (
            f"{name} must be exported on window.NBIO_APPLY for unit testing"
        )
