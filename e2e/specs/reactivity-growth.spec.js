// @ts-check
// AUDIT GAP G1 — a partner's weight log never reaches this tab's header chip.
// connectSSE (app.js:1762-1775) registers NO `growth.*` listener, though the
// server publishes growth.created (routes/growth.py:38). Only the posting device
// updates the chip (settings.js refreshHeaderWeight). = #81 bug (b). Fixed in PR-B3.
//
// Robust on the shared DB: read the partner's CURRENT chip value, post a DIFFERENT
// weight from the other parent, assert the partner moves to it (so a stale
// first-paint value can never make this pass by accident).
const { test, expect } = require("@playwright/test");

const CHIP = "[data-baby-weight]";
// Grams as an integer, stripping the thousands separator and " g" suffix. The
// server renders en-US comma-grouped ("3,420 g"); comparing the parsed integer
// keeps the assertion locale-immune (cf. the S1 spec's integer deltas).
const grams = async (loc) => parseInt(((await loc.textContent()) || "").replace(/[^0-9]/g, ""), 10);

test("G1: partner header weight chip updates when the other parent logs a weight", async ({ browser }) => {
  test.fail();
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
