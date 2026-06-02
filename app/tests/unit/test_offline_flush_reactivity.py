"""
Source-level pins for the offline-flush double-count fix (PR-B5).

Bug: an offline-queued create applies its optimistic count (+1) and remembers its
idem in `ownIdems` with a 60s TTL. On reconnect, `flushOutbox` POSTs — possibly
>60s later — and the server's `event.created` SSE echo arrives with the TTL
already lapsed, so `suppress` is false and the count bumps a SECOND time
(double-count). A page that was RELOADED while offline must still bump on the echo
(its load-time count excluded the queued event), so the fix must be session-aware,
NOT a blanket suppression.

Fix: an in-memory `pendingOptimistic` Set of idems optimistically applied THIS
session and awaiting flush. `flushOutbox` re-keys `ownIdems` (refreshing the TTL)
for those items BEFORE issuing the POST — so the imminent echo is suppressed even
if it arrives before the fetch resolves. A reloaded session starts with an empty
Set, so its echo correctly bumps. These pins guard the structure; the behaviour is
proven by `e2e/specs/reactivity-offline.spec.js`.
"""

from __future__ import annotations

from pathlib import Path

APP_JS = Path(__file__).resolve().parents[2] / "nbio" / "static" / "app.js"


def _fn_body(src: str, signature: str) -> str:
    idx = src.find(signature)
    assert idx >= 0, f"{signature!r} not found"
    end = src.find("\n  }", idx)
    return src[idx : end if end > idx else idx + 2000]


def test_pending_optimistic_set_declared() -> None:
    src = APP_JS.read_text()
    assert "pendingOptimistic" in src and "new Set(" in src, (
        "an in-memory pendingOptimistic Set must track idems optimistically "
        "applied this session and awaiting flush."
    )


def test_enqueue_path_marks_the_idem_optimistic() -> None:
    # The offline branch of submitCreate (the only IDB.enqueue site) must record
    # the idem as optimistically-applied this session.
    src = APP_JS.read_text()
    idx = src.find("IDB.enqueue(")
    assert idx >= 0, "IDB.enqueue site not found"
    window = src[idx - 400 : idx + 400]
    assert "pendingOptimistic.add(" in window, (
        "the offline enqueue path must add the idem to pendingOptimistic so the "
        "later flush knows WE already counted it this session."
    )


def test_flush_rekeys_ownidem_before_the_fetch() -> None:
    body = _fn_body(APP_JS.read_text(), "async function flushOutbox(")
    rekey = body.find("rememberOwnIdem(")
    fetch = body.find("await fetch(")
    guard = body.find("pendingOptimistic.has(")
    assert rekey >= 0, "flushOutbox must re-key ownIdems for session-pending items"
    assert guard >= 0, "the re-key must be guarded by pendingOptimistic.has(...)"
    assert fetch >= 0, "flushOutbox must POST each item"
    # The crux: re-keying AFTER the fetch would lose the race when the SSE echo
    # arrives before the POST resolves. It must come BEFORE the fetch.
    assert rekey < fetch, (
        "rememberOwnIdem(it.idem) must run BEFORE `await fetch` — otherwise the "
        "event.created echo can land (un-suppressed) before the re-key and "
        "double-count."
    )
    assert guard < fetch, "the pendingOptimistic.has guard must also precede the fetch"


def test_flush_clears_pending_on_dequeue() -> None:
    body = _fn_body(APP_JS.read_text(), "async function flushOutbox(")
    assert "pendingOptimistic.delete(" in body, (
        "flushOutbox must remove the idem from pendingOptimistic once successfully "
        "dequeued (it is no longer awaiting flush)."
    )
