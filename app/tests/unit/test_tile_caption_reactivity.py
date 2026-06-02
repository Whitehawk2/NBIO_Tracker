"""
Source-level pins for the per-type tile-button "last X ago" caption reactivity
(PR-B4b). Sibling of test_last_of_each_reactivity.py: the today-card row (#103)
and the tile captions are the same bug class on different surfaces.

The tile captions (`#ago-{breast,formula,wee,poo}`) show each TYPE's most-recent
event. A fourth updater (`tileCaptionUpdater`) on the applyEvent seam keeps them
live. Pins guard the decisions the design review fixed:
  - registered into the seam (else it never runs),
  - UPSERT-ONLY (delete-recompute deferred to #93's store),
  - per-TYPE not lane (breast and formula are separate tiles; must NOT collapse
    to the combined "feed" lane and cross-update),
  - renderTileCaption injects via DOM nodes / properties, never `.innerHTML`
    (actor_color -> .style.background, actor_name -> .title, brand -> textContent),
  - it stamps `dataset.lastId` so the (occurred_at, id) tie-break stays correct
    (the "right text, stale key" trap).
Runtime behaviour is covered by reactivity-tile-caption.spec.js + the Vitest units.
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "nbio" / "static"
APP_JS = STATIC / "app.js"
APPLY_JS = STATIC / "apply-event.js"


def _fn_body(src: str, signature: str) -> str:
    idx = src.find(signature)
    assert idx >= 0, f"{signature!r} not found"
    end = src.find("\n  }", idx)
    return src[idx : end if end > idx else idx + 2000]


def test_updater_is_registered_into_the_seam() -> None:
    assert "APPLY.registerUpdater(tileCaptionUpdater)" in APP_JS.read_text(), (
        "tileCaptionUpdater must be registered into the applyEvent seam, or the "
        "tile captions never update."
    )


def test_updater_is_upsert_only_and_per_type() -> None:
    body = _fn_body(APP_JS.read_text(), "function tileCaptionUpdater(")
    assert "rowAction(" in body and '"upsert"' in body, (
        "tileCaptionUpdater must be upsert-only (delete-recompute is #93's store)."
    )
    # Per-TYPE: keyed by tileCaptionType + getElementById(`ago-${t}`) — NOT laneForType
    # (which collapses breast+formula to "feed" and would cross-update the tiles).
    assert "tileCaptionType(" in body, "must key the tile per-type, not by feed lane"
    assert "laneForType(" not in body, (
        "tileCaptionUpdater must NOT use laneForType — that combines breast+formula "
        "into one lane and would cross-update the separate tiles."
    )
    assert "ago-" in body, "must target the #ago-<type> tile caption element"


def test_render_uses_dom_nodes_not_innerhtml() -> None:
    body = _fn_body(APP_JS.read_text(), "function renderTileCaption(")
    assert ".innerHTML" not in body, (
        "renderTileCaption must not use .innerHTML — actor_name/brand are free text "
        "and would become markup (XSS). Use createElement + textContent + properties."
    )
    # actor_color/name go through element PROPERTIES (CSS/attribute context), not
    # string-built markup; brand goes through textContent.
    assert ".style.background" in body, "actor_color must set .style.background (not markup)"
    assert ".title" in body, "actor_name must set .title (not markup)"
    assert "textContent" in body, "the relative-time / brand text must be set via textContent"
    assert "dataset.lastId" in body, (
        "renderTileCaption must stamp dataset.lastId so the (occurred_at, id) "
        "tie-break stays correct after a JS render (avoid the stale-key trap)."
    )


def test_pure_helper_exported_and_distinct_from_lane() -> None:
    src = APPLY_JS.read_text()
    assert "function tileCaptionType(" in src, "tileCaptionType must be defined in apply-event.js"
    assert "tileCaptionType" in src.split("window.NBIO_APPLY = {", 1)[1], (
        "tileCaptionType must be exported on window.NBIO_APPLY for unit testing"
    )
