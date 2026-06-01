"""
Source-level pin for the sync-badge connection state.

Production/CI finding: `bumpPending()` runs at init right after `connectSSE()`
and used to call `setSyncState("offline")` UNCONDITIONALLY. Because its
`await IDB.countOutbox()` can resolve AFTER the SSE `onopen` sets "connected",
the unconditional offline clobbered "connected" back to a misleading "offline"
that stuck until the next state change — a real UX bug on slow first connects
and the cause of the e2e SSE-barrier flake.

Contract pinned here: `bumpPending` must only claim "offline" when something is
actually queued (n > 0), mirroring `flushOutbox`. We read app.js as text rather
than under a browser (the JS behaviour itself is covered by the e2e barrier).
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[2] / "nbio" / "static" / "app.js"


def _bump_pending_body() -> str:
    src = APP_JS.read_text()
    idx = src.find("async function bumpPending(")
    assert idx >= 0, "bumpPending() not found in app.js"
    # Bound to the function body (its first 2-space-indented closing brace).
    end = src.find("\n  }", idx)
    return src[idx : end if end > idx else idx + 600]


def test_bump_pending_only_goes_offline_when_items_are_queued():
    body = _bump_pending_body()
    all_offline = re.findall(r'setSyncState\(\s*"offline"\s*\)', body)
    guarded_offline = re.findall(
        r'if\s*\(\s*n\s*>\s*0\s*\)[\s\S]{0,40}setSyncState\(\s*"offline"\s*\)',
        body,
    )
    # It must still be ABLE to show offline (the queued-items case)...
    assert all_offline, "bumpPending should still set 'offline' when the outbox has items"
    # ...and EVERY offline transition must be guarded by `if (n > 0)`. Counting
    # total vs guarded catches a reintroduced UNCONDITIONAL offline alongside the
    # guarded one — that at init clobbers the SSE 'connected' state (UX bug on
    # slow connects; flaked the e2e SSE barrier).
    assert len(all_offline) == len(guarded_offline), (
        "bumpPending has an unconditional setSyncState('offline') — every offline "
        "transition must be guarded by `if (n > 0)`."
    )
