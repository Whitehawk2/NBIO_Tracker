/* NBIO Tracker — applyEvent dispatch seam (issue #81 reactivity router).
 *
 * ONE fan-out every event path calls, so "which home-page surfaces refresh"
 * is decided in a single place instead of re-derived (and partially forgotten)
 * at each call site. This module is deliberately DOM-FREE: it derives a count
 * delta + a row action from an event's lifecycle action and hands them to
 * registered updaters. app.js owns the concrete DOM updaters and registers them
 * at init; #93's hybrid store will register store-diffing updaters instead,
 * leaving this dispatch core untouched.
 *
 * Loaded as its own <script> before app.js (mirrors idb.js / window.NBIO_IDB)
 * so window.NBIO_APPLY exists when app.js runs and so the dispatch logic is
 * unit-testable in jsdom without app.js's load-time side effects.
 *
 * Behavior note (PR-B1 is behavior-preserving): own-echo SUPPRESSION is NOT
 * owned here — callers compute ctx.suppress with the existing ownIdems /
 * ownDeletes keying and pass it in, so this seam reproduces today's behavior
 * exactly (including the unsuppressed-undelete quirk tracked in #98). Unifying
 * suppression belongs to #93's dedup.
 */
(function () {
  "use strict";

  // The single source of truth for count direction per lifecycle action.
  // created / undeleted add a row to a day; deleted removes one; updated and
  // reconciled change no count (a row edit or an optimistic->server id swap).
  const DELTA = { created: 1, undeleted: 1, deleted: -1, updated: 0, reconciled: 0 };

  function deltaFor(action) {
    return Object.prototype.hasOwnProperty.call(DELTA, action) ? DELTA[action] : 0;
  }

  // Which row operation an action implies. "remove" drops the row; "reconcile"
  // swaps an optimistic local: row for the server row (keyed by ctx.idem);
  // "upsert" inserts-or-updates (created / updated / undeleted).
  function rowAction(action) {
    if (action === "deleted") return "remove";
    if (action === "reconciled") return "reconcile";
    return "upsert";
  }

  // Whether the count surfaces (today-card cells, last-3-days table, banners)
  // should move. Skip when the delta is zero (edit / reconcile) or when this is
  // our own SSE echo (already applied optimistically) — see ctx.suppress.
  function shouldCount(ctx) {
    return ctx.delta !== 0 && !ctx.suppress;
  }

  // Ordered registry of `(ev, ctx) => void` updaters. Order is a contract:
  // updaters must be independent — count/recompute updaters receive a fully
  // resolved `ev` and MUST NOT read the live event row by id (so a later
  // last-of-each recompute can't depend on whether the row is still in the DOM).
  let updaters = [];
  function registerUpdater(fn) {
    updaters.push(fn);
  }
  function resetUpdaters() {
    updaters = [];
  }

  // The fan-out. ev is the (optimistic or server) event object; on a delete the
  // caller MUST pass the resolved event (row.__event), not the {id}-only SSE
  // wire payload, or the decrement has nothing to act on. ctx:
  //   { action, source?, idem?, suppress? }
  // delta is derived here and added to the ctx every updater receives. An
  // unrecognised action is a no-op (touches no updater = no surface moves).
  function applyEvent(ev, ctx) {
    const action = ctx && ctx.action;
    if (!Object.prototype.hasOwnProperty.call(DELTA, action)) return;
    const full = {
      action,
      source: (ctx && ctx.source) || "local",
      idem: ctx && ctx.idem,
      suppress: !!(ctx && ctx.suppress),
      delta: DELTA[action],
    };
    for (const fn of updaters) fn(ev, full);
  }

  window.NBIO_APPLY = {
    applyEvent,
    registerUpdater,
    resetUpdaters,
    deltaFor,
    rowAction,
    shouldCount,
  };
})();
