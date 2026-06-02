// apply-event.js — dispatch-seam contract (PR-B1; the #81 reactivity router
// that #93's hybrid store will inherit).
//
// The seam is DOM-free: from an event's lifecycle action it derives a count
// delta + a row action, then fans out to registered updaters. The concrete DOM
// updaters (insertOrUpdateRow / bumpOverviews / removeRow / replaceOptimistic)
// live in app.js and are registered at init; here we drive the seam with SPY
// updaters so the dispatch logic is proven in ISOLATION from the DOM. The glue
// that maps a decision onto a DOM call is exercised by the E2E S1 reactivity
// lock, which must stay green across this behavior-preserving PR.
//
// These pin the behavior-preservation traps the design review surfaced:
//   - own SSE echo: suppress the count but STILL upsert the row,
//   - reconcile / offline-flush response: swap the row, NO bump,
//   - edit (updated): row-only, no count change,
//   - delete: remove + decrement once,
// plus the action->delta map and the registry fan-out.

import { describe, it, expect, beforeAll, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

beforeAll(() => {
  const src = readFileSync(join(__dirname, "..", "static", "apply-event.js"), "utf-8");
  // Indirect eval in global scope so window.NBIO_APPLY lands on jsdom's window
  // (same idiom setup.js uses for idb.js). The source is checked into the repo,
  // not untrusted input.
  // eslint-disable-next-line no-eval
  (0, eval)(src);
});

describe("NBIO_APPLY.deltaFor", () => {
  it("created and undeleted are +1", () => {
    expect(window.NBIO_APPLY.deltaFor("created")).toBe(1);
    expect(window.NBIO_APPLY.deltaFor("undeleted")).toBe(1);
  });
  it("deleted is -1", () => {
    expect(window.NBIO_APPLY.deltaFor("deleted")).toBe(-1);
  });
  it("updated and reconciled are 0 (row-only, no count change)", () => {
    expect(window.NBIO_APPLY.deltaFor("updated")).toBe(0);
    expect(window.NBIO_APPLY.deltaFor("reconciled")).toBe(0);
  });
  it("an unknown action is 0", () => {
    expect(window.NBIO_APPLY.deltaFor("bogus")).toBe(0);
  });
});

describe("NBIO_APPLY.rowAction", () => {
  it("deleted -> remove", () => expect(window.NBIO_APPLY.rowAction("deleted")).toBe("remove"));
  it("reconciled -> reconcile", () => expect(window.NBIO_APPLY.rowAction("reconciled")).toBe("reconcile"));
  it("created/updated/undeleted -> upsert", () => {
    for (const a of ["created", "updated", "undeleted"]) {
      expect(window.NBIO_APPLY.rowAction(a)).toBe("upsert");
    }
  });
});

describe("NBIO_APPLY.shouldCount", () => {
  it("true only when delta != 0 and not suppressed", () => {
    expect(window.NBIO_APPLY.shouldCount({ delta: 1, suppress: false })).toBe(true);
    expect(window.NBIO_APPLY.shouldCount({ delta: -1, suppress: false })).toBe(true);
  });
  it("false when delta is 0 (updated / reconciled)", () => {
    expect(window.NBIO_APPLY.shouldCount({ delta: 0, suppress: false })).toBe(false);
  });
  it("false when suppressed (own SSE echo), even with a non-zero delta", () => {
    expect(window.NBIO_APPLY.shouldCount({ delta: 1, suppress: true })).toBe(false);
  });
});

describe("NBIO_APPLY.countOps", () => {
  // The count-surface operations an action implies: a list of [event, delta]
  // pairs the caller applies via bumpOverviews. Pinned here so the DOM-free
  // decision is proven without the DOM.
  it("created -> add the new event once", () => {
    expect(window.NBIO_APPLY.countOps({ id: 1 }, { action: "created", delta: 1, suppress: false }))
      .toEqual([[{ id: 1 }, 1]]);
  });
  it("deleted -> remove the event once", () => {
    expect(window.NBIO_APPLY.countOps({ id: 1 }, { action: "deleted", delta: -1, suppress: false }))
      .toEqual([[{ id: 1 }, -1]]);
  });
  it("own-echo (suppress) -> no count op, but the row still upserts elsewhere", () => {
    expect(window.NBIO_APPLY.countOps({ id: 1 }, { action: "created", delta: 1, suppress: true }))
      .toEqual([]);
  });
  it("reconciled / delta 0 -> no count op (flush + edit-reconcile do no bump)", () => {
    expect(window.NBIO_APPLY.countOps({ id: 1 }, { action: "reconciled", delta: 0, suppress: false }))
      .toEqual([]);
  });
  it("updated with prev -> remove the old contribution, add the new (the edit diff)", () => {
    const prev = { id: 1, occurred_at: "old" };
    const next = { id: 1, occurred_at: "new" };
    expect(window.NBIO_APPLY.countOps(next, { action: "updated", delta: 0, prev }))
      .toEqual([[prev, -1], [next, 1]]);
  });
  it("updated without prev -> add the new contribution only (fallback)", () => {
    const next = { id: 1 };
    expect(window.NBIO_APPLY.countOps(next, { action: "updated", delta: 0 }))
      .toEqual([[next, 1]]);
  });
  it("updated ignores suppress — own echoes rely on the live-prev net-zero, not suppression", () => {
    const prev = { id: 1, occurred_at: "old" };
    const next = { id: 1, occurred_at: "new" };
    expect(window.NBIO_APPLY.countOps(next, { action: "updated", delta: 0, suppress: true, prev }))
      .toEqual([[prev, -1], [next, 1]]);
  });
});

describe("NBIO_APPLY.applyEvent dispatch", () => {
  let calls;
  beforeEach(() => {
    window.NBIO_APPLY.resetUpdaters();
    calls = [];
    window.NBIO_APPLY.registerUpdater((ev, ctx) => calls.push(["A", ev, ctx]));
    window.NBIO_APPLY.registerUpdater((ev, ctx) => calls.push(["B", ev, ctx]));
  });

  it("fans out to every registered updater, in registration order", () => {
    window.NBIO_APPLY.applyEvent({ id: 1 }, { action: "created" });
    expect(calls.map((c) => c[0])).toEqual(["A", "B"]);
  });

  it("passes the event object through unchanged", () => {
    const ev = { id: 7, type: "wee" };
    window.NBIO_APPLY.applyEvent(ev, { action: "created" });
    expect(calls[0][1]).toBe(ev);
  });

  it("derives delta from the action and puts it in ctx", () => {
    window.NBIO_APPLY.applyEvent({ id: 1 }, { action: "deleted" });
    expect(calls[0][2].delta).toBe(-1);
  });

  it("defaults source to 'local' and carries action/idem/suppress through", () => {
    // Two updaters are registered, so each applyEvent pushes two calls (A, B).
    window.NBIO_APPLY.applyEvent({ id: 1 }, { action: "reconciled", idem: "x1" });
    expect(calls[0][2]).toMatchObject({ action: "reconciled", source: "local", idem: "x1", delta: 0 });

    window.NBIO_APPLY.applyEvent({ id: 2 }, { action: "created", source: "sse", suppress: true });
    expect(calls[2][2]).toMatchObject({ action: "created", source: "sse", suppress: true, delta: 1 });
  });

  it("carries ctx.prev through to updaters (the edit diff needs the pre-edit event)", () => {
    const prev = { id: 9, occurred_at: "old" };
    window.NBIO_APPLY.applyEvent({ id: 9 }, { action: "updated", prev });
    expect(calls[0][2].prev).toBe(prev);
  });

  it("is a no-op for an unknown action — touches NO updater, so no surface moves", () => {
    window.NBIO_APPLY.applyEvent({ id: 1 }, { action: "bogus" });
    expect(calls).toHaveLength(0);
  });

  it("resetUpdaters clears the registry", () => {
    window.NBIO_APPLY.resetUpdaters();
    window.NBIO_APPLY.applyEvent({ id: 1 }, { action: "created" });
    expect(calls).toHaveLength(0);
  });
});

describe("call-site scenarios (the review's behavior-preservation traps)", () => {
  // Collapse the seam's decision helpers the way the app.js updaters consult
  // them, so each real call site reads as one row/counts expectation.
  const scenario = (ctx) => {
    const delta = window.NBIO_APPLY.deltaFor(ctx.action);
    return {
      row: window.NBIO_APPLY.rowAction(ctx.action),
      counts: window.NBIO_APPLY.shouldCount({ delta, suppress: !!ctx.suppress }),
    };
  };

  it("own SSE 'created' echo: row upserts, count is SUPPRESSED", () => {
    expect(scenario({ action: "created", source: "sse", suppress: true }))
      .toEqual({ row: "upsert", counts: false });
  });
  it("remote SSE 'created': row upserts, count bumps once", () => {
    expect(scenario({ action: "created", source: "sse", suppress: false }))
      .toEqual({ row: "upsert", counts: true });
  });
  it("'updated' (edit): row-only, no count change", () => {
    expect(scenario({ action: "updated" })).toEqual({ row: "upsert", counts: false });
  });
  it("'reconciled' (POST / offline-flush response): swaps the row, NO bump", () => {
    expect(scenario({ action: "reconciled" })).toEqual({ row: "reconcile", counts: false });
  });
  it("'deleted': removes the row and decrements once", () => {
    expect(scenario({ action: "deleted" })).toEqual({ row: "remove", counts: true });
  });
  it("own-echo SSE 'deleted': row is STILL removed, count SUPPRESSED", () => {
    // The highest-risk trap: suppress must gate only the count, never the row
    // removal (else our own delete echo would leave the row behind).
    expect(scenario({ action: "deleted", suppress: true })).toEqual({ row: "remove", counts: false });
  });
  it("'undeleted': re-inserts the row and increments", () => {
    expect(scenario({ action: "undeleted" })).toEqual({ row: "upsert", counts: true });
  });
});

// Growth (weight) helpers — pure, used by app.js's header-weight chip updater
// (G1). Growth is not an event-list event, so it bypasses the dispatch registry;
// these live on the seam only so they're unit-testable (app.js is a closed IIFE).
describe("NBIO_APPLY.fmtGrams", () => {
  it("comma-groups thousands and appends ' g'", () => {
    expect(window.NBIO_APPLY.fmtGrams(900)).toBe("900 g");
    expect(window.NBIO_APPLY.fmtGrams(3420)).toBe("3,420 g");
    expect(window.NBIO_APPLY.fmtGrams(12345)).toBe("12,345 g");
  });
});

describe("NBIO_APPLY.isNewerGrowth", () => {
  it("accepts the first event (no prior key)", () => {
    expect(window.NBIO_APPLY.isNewerGrowth({ measured_at: "2026-06-01", id: 5 }, null)).toBe(true);
  });
  it("accepts a later measurement date", () => {
    expect(
      window.NBIO_APPLY.isNewerGrowth({ measured_at: "2026-06-02", id: 1 }, { measured_at: "2026-06-01", id: 9 }),
    ).toBe(true);
  });
  it("rejects an earlier date (don't clobber the chip with a stale weight)", () => {
    expect(
      window.NBIO_APPLY.isNewerGrowth({ measured_at: "2026-05-30", id: 99 }, { measured_at: "2026-06-01", id: 1 }),
    ).toBe(false);
  });
  it("same date: accepts same-or-higher id (update or newer row), rejects lower", () => {
    const last = { measured_at: "2026-06-01", id: 7 };
    expect(window.NBIO_APPLY.isNewerGrowth({ measured_at: "2026-06-01", id: 7 }, last)).toBe(true);
    expect(window.NBIO_APPLY.isNewerGrowth({ measured_at: "2026-06-01", id: 8 }, last)).toBe(true);
    expect(window.NBIO_APPLY.isNewerGrowth({ measured_at: "2026-06-01", id: 6 }, last)).toBe(false);
  });
});
