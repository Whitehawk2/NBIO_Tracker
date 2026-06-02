// @ts-check
// PR-B4b — the per-type tile-button "last X ago" captions (#ago-<type>) must
// update live, like the today-card row did in #103 (G4). Field-found 2026-06-02:
// after PWA A logged a formula, PWA B's today-card overview updated but the
// Formula TILE still showed "3 hours ago" until reload, because refreshRelTimes()
// only rewrites the relative TEXT from the existing data-rel attribute — it never
// swaps the attribute to a newer event. A fourth seam updater (tileCaptionUpdater)
// fixes it. Upsert-only by design (delete-recompute deferred to #93).
//
// Per-TYPE surface: this asserts the FORMULA tile, keyed off the formula tile's
// OWN current data-rel (not the combined feed row), so a formula log can't pass by
// coincidentally matching the feed cell. Hour-of-day independent: the UI clamps a
// log to <= now, so we post (other parent, SSE path) a formula stamped strictly
// after the current latest FORMULA and assert the tile converges to it.
const { test, expect } = require("@playwright/test");

const AGO_FORMULA_REL = "#ago-formula span[data-rel]";

function isoPlusMinutes(iso, mins) {
  return new Date(new Date(iso).getTime() + mins * 60000).toISOString();
}

test("B4b: the Formula tile 'last ago' caption updates live when a newer formula is logged", async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "playwright/.auth/parent-a.json" });
  const a = await ctx.newPage();
  try {
    await a.goto("/");
    await expect(a.locator("#sync-badge .sync-dot")).toHaveAttribute("data-state", "connected");

    await expect(a.locator(AGO_FORMULA_REL)).toBeVisible();
    const before = await a.locator(AGO_FORMULA_REL).getAttribute("data-rel");
    expect(before, "a seeded last-formula exists on the tile at first paint").toBeTruthy();

    const next = isoPlusMinutes(before, 1); // strictly newer than the current latest formula
    const idem = `b4b-${next}-${Date.now()}`;
    // Posted via the raw API (not the page's submitCreate), so it reaches this tab
    // purely over SSE — this spec exercises the remote/SSE path of tileCaptionUpdater
    // (the harder-to-regress one); the optimistic path shares the same updater.
    const r = await ctx.request.post("/api/events", {
      data: {
        type: "formula",
        formula_volume_ml: 30,
        formula_brand: "Aptamil",
        occurred_at: next,
        idempotency_key: idem,
        created_by_device: "e2e-parent-a",
      },
    });
    expect(r.ok(), "formula POST landed").toBeTruthy();

    // The event reaches this tab over SSE and the seam inserts its row; read the
    // row's OWN delivered occurred_at so the assertion can't drift on normalisation.
    const newRow = a.locator(`#event-list li[data-idem="${idem}"]`);
    await expect(newRow).toBeVisible();
    const newRel = await newRow.locator("[data-rel]").getAttribute("data-rel");
    expect(newRel, "the new formula row carries a relative-time stamp").toBeTruthy();
    expect(newRel).not.toBe(before); // genuinely newer than the prior tile value

    // DESIRED (B4b): the Formula tile caption now shows that exact event.
    await expect(a.locator(AGO_FORMULA_REL)).toHaveAttribute("data-rel", newRel);
    // ...and the JS-rendered caption reproduces the formula-only brand detail
    // (proves renderTileCaption's per-type branch, not just the timestamp swap).
    await expect(a.locator("#ago-formula .muted")).toContainText("Aptamil");
  } finally {
    await ctx.close();
  }
});
