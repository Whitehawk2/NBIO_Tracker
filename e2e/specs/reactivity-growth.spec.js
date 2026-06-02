// @ts-check
// G1 — a partner's weight log must reach this tab's header chip live. PR-B3 adds
// `growth.*` SSE listeners in connectSSE that update [data-baby-weight] (the
// server publishes the full growth row; settings.js only updates the poster's
// own chip and isn't even loaded on the home page). = #81 bug (b).
//
// Robust on the shared DB: read the partner's CURRENT chip value, post a DIFFERENT
// weight from the other parent, assert the partner moves to it (so a stale
// first-paint value can never make this pass by accident). NOTE: G1 going green
// also relies on growth NOT being SSE-replayed + seed/POST sharing today's date,
// so the partner's first growth event is always accepted (see isNewerGrowth).
const { test, expect } = require("@playwright/test");

const CHIP = "[data-baby-weight]";
// Grams as an integer, stripping the thousands separator and " g" suffix. The
// server renders en-US comma-grouped ("3,420 g"); comparing the parsed integer
// keeps the assertion locale-immune (cf. the S1 spec's integer deltas).
const grams = async (loc) => parseInt(((await loc.textContent()) || "").replace(/[^0-9]/g, ""), 10);

test("G1: partner header weight chip updates when the other parent logs a weight", async ({ browser }) => {
  const ctxA = await browser.newContext({ storageState: "playwright/.auth/parent-a.json" });
  const ctxB = await browser.newContext({ storageState: "playwright/.auth/parent-b.json" });
  const a = await ctxA.newPage();
  const b = await ctxB.newPage();
  try {
    await a.goto("/");
    await b.goto("/");
    for (const pg of [a, b]) {
      await expect(pg.locator("#sync-badge .sync-dot")).toHaveAttribute("data-state", "connected");
    }

    // Partner B's current weight (the seeded baseline, possibly bumped by a prior run).
    await expect(b.locator(CHIP)).toBeVisible();
    const current = await grams(b.locator(CHIP));
    const next = current + 100;

    // Parent A logs a NEW weight. The gap is B's missing SSE listener, so the
    // poster mechanism is incidental — post via the API from A's context.
    const r = await ctxA.request.post("/api/growth", {
      data: {
        weight_g: next,
        measured_at: new Date().toISOString().slice(0, 10),
        idempotency_key: `g1-${next}-${Date.now()}`,
        created_by_device: "e2e-parent-a",
      },
    });
    expect(r.ok(), "growth POST landed").toBeTruthy();

    // DESIRED: B's header chip reflects the partner's new weight via SSE. Poll the
    // parsed integer so we wait out SSE delivery without coupling to text format.
    await expect.poll(() => grams(b.locator(CHIP))).toBe(next);
  } finally {
    await ctxA.close();
    await ctxB.close();
  }
});
