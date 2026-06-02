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
  // should move. Skip when the delta is zero (reconcile) or when this is our own
  // SSE echo (already applied optimistically) — see ctx.suppress.
  function shouldCount(ctx) {
    return ctx.delta !== 0 && !ctx.suppress;
  }

  // The count-surface operations an action implies, as [event, delta] pairs the
  // caller applies via bumpOverviews. An edit (updated) is modelled as
  // remove-the-old-contribution + add-the-new, so every aggregate (counts,
  // formula cc, vit-D/tummy banners, day buckets) recomputes from the existing
  // bumpOverviews logic without bespoke per-surface edit code. Own-echo edits
  // are NOT suppressed: by the time our own SSE echo lands, the live `prev` the
  // caller captured already equals the new event, so [-1,+1] nets to zero.
  function countOps(ev, ctx) {
    if (ctx.action === "updated") {
      const ops = [];
      if (ctx.prev) ops.push([ctx.prev, -1]);
      ops.push([ev, 1]);
      return ops;
    }
    return shouldCount(ctx) ? [[ev, ctx.delta]] : [];
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
      prev: ctx && ctx.prev,
      delta: DELTA[action],
    };
    for (const fn of updaters) fn(ev, full);
  }

  // ----- growth (weight) helpers (G1). Growth is NOT an event-list event (no
  // row, no count/delta), so it does NOT go through the dispatch registry above
  // — app.js wires a dedicated growth.* SSE listener to the header-weight chip.
  // These two pure helpers live here only so they're unit-testable (app.js is a
  // closed IIFE that exposes nothing).
  function fmtGrams(grams) {
    return `${String(grams).replace(/\B(?=(\d{3})+(?!\d))/g, ",")} g`;
  }
  // The header chip shows the LATEST weight. Accept an incoming growth row only
  // if it is at least as recent as the last one applied: a newer measurement
  // date, or the same date with an id >= the last (an update of the shown row,
  // or a newer same-day measurement). A null lastKey accepts the first event.
  function isNewerGrowth(incoming, lastKey) {
    if (!lastKey) return true;
    if (incoming.measured_at > lastKey.measured_at) return true;
    if (incoming.measured_at < lastKey.measured_at) return false;
    return incoming.id >= lastKey.id;
  }

  // ----- last-of-each (G4) pure helpers. The today-card "last feed/wee/poo"
  // cells show the ALL-TIME most-recent non-deleted event of each lane (feed =
  // breast OR formula), so app.js wires a dedicated last-of-each updater that
  // re-renders a cell when an incoming event is at least as recent as the one it
  // shows. UPSERT-ONLY by design: created/undeleted/updated compare the passed
  // `ev` against the cell's current key — never reading DOM rows, honouring the
  // seam's "MUST NOT read the live event row by id" contract above. Delete-
  // recompute of the displayed-last needs the full event set (older than the
  // event-list's ~2-day window), so it's deferred to #93's hybrid store. These
  // helpers are pure so they're unit-testable; app.js owns the DOM glue.

  // event type -> today-card last-of-each lane key, or null for types with no
  // such cell (vitd / tummy_time live in their own banners). Mirrors countKey's
  // breast+formula -> "feed" combining, but keyed to the data-last cells.
  function laneForType(type) {
    if (type === "breast" || type === "formula") return "feed";
    if (type === "wee" || type === "poo") return type;
    return null;
  }

  // An optimistic, not-yet-reconciled event id ("local:uuid"), as minted by the
  // create path before the server assigns a real integer id.
  function isLocalId(id) {
    return typeof id === "string" && id.startsWith("local:");
  }

  // Whether `incoming` should replace the event a last-of-each cell currently
  // shows. The cell shows the latest by (occurred_at, id); accept a strictly
  // newer measurement, or an equal occurred_at with id >= current (a newer
  // same-instant event, or a re-render of the shown one). A null currentKey
  // (empty "never" cell) or a missing current id (fresh server render) accepts.
  // Optimistic "local:" ids are NOT comparable to server integers, so an
  // optimistic value on EITHER side accepts: this is what unsticks the cell when
  // an optimistic create's own server echo (real id) lands at the SAME instant —
  // a raw `>=` would compute `42 >= "local:.."` => `42 >= NaN` => false and
  // reject the real event forever. Real ids compare numerically (dataset
  // attributes stringify them). Same tie-break spirit as isNewerGrowth.
  function lastCellWins(incoming, currentKey) {
    if (!currentKey) return true;
    if (incoming.occurred_at > currentKey.occurred_at) return true;
    if (incoming.occurred_at < currentKey.occurred_at) return false;
    if (currentKey.id == null) return true;
    if (isLocalId(currentKey.id) || isLocalId(incoming.id)) return true;
    return Number(incoming.id) >= Number(currentKey.id);
  }

  // The PLAIN-TEXT detail suffix for a last-of-each cell, mirroring the
  // today_card.html template's per-lane fields. Returns text only (with leading
  // " · " separators) — NO markup — so the caller injects it via textContent and
  // free-text notes can never become HTML. Pre-escaping here would double-encode.
  function lastSuffix(lane, ev) {
    const parts = [];
    if (lane === "feed") {
      if (ev.feed_side) parts.push(ev.feed_side);
      if (ev.feed_duration_min) parts.push(`${ev.feed_duration_min} min`);
    } else if (lane === "wee") {
      if (ev.notes) parts.push(ev.notes);
    } else if (lane === "poo") {
      if (ev.poo_quality) parts.push(`type ${ev.poo_quality}`);
      if (ev.notes) parts.push(ev.notes);
    }
    return parts.map((p) => ` · ${p}`).join("");
  }

  window.NBIO_APPLY = {
    applyEvent,
    registerUpdater,
    resetUpdaters,
    deltaFor,
    rowAction,
    shouldCount,
    countOps,
    fmtGrams,
    isNewerGrowth,
    laneForType,
    lastCellWins,
    lastSuffix,
  };
})();
