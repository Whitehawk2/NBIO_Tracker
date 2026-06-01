// @ts-check
// AUDIT GAP G3 — editing an event refreshes the event row but NOT the banner.
// `submitEdit` (app.js:856) and the SSE `event.updated` handler (app.js:1763)
// both call only `insertOrUpdateRow`; neither re-renders the vit-D/tummy banner.
// Verified by MCP probe 2026-06-01: after editing a vit-D's time, the row moved
// to the new time while the banner stayed frozen at the original.
//
// test.fail(): this asserts the DESIRED post-fix behaviour (the banner follows
// the edit). It RUNS, fails today (the gap, proven continuously in CI), and
// ALARMS the moment a fix lands. Fixed in PR-B2.
const { test, expect } = require("@playwright/test");

test("G3: vit-D banner follows an edit of the vit-D event's time", async ({ browser }) => {
  test.fail();
  const ctx = await browser.newContext({ storageState: "playwright/.auth/parent-a.json" });
  const a = await ctx.newPage();
  try {
    await a.goto("/");
    await expect(a.locator("#sync-badge .sync-dot")).toHaveAttribute("data-state", "connected");

    const vitdRow = a.locator('.event-list li[data-type="vitd"]').first();
    await expect(vitdRow).toBeVisible();
    const rowWhen = vitdRow.locator("[data-rel]").first();
    const bannerWhen = a.locator("[data-vitd-banner] .when[data-rel]");
    await expect(bannerWhen).toBeVisible();

    // The row and the banner summarise the SAME event, so their data-rel values
    // start equal; after the fix they should END equal too. Capture the pre-edit
    // time to anchor the "row actually moved" wait below.
    const beforeRel = await rowWhen.getAttribute("data-rel");

    // Edit the vit-D event's time to "now" via the row's ⋯ menu.
    await vitdRow.locator(".row-menu").click();
    await a.locator('.modal-backdrop button:has-text("Edit")').click();
    const modal = a.locator(".modal-sheet");
    await expect(modal).toBeVisible();
    await modal.locator('.time-chips .chip[data-label="now"]').click();
    await modal.locator(".btn-primary").click(); // "Save changes"
    await expect(modal).toBeHidden();

    // submitEdit (app.js:846) closes the modal SYNCHRONOUSLY, then awaits the
    // PATCH and only re-renders the row via insertOrUpdateRow on the response —
    // there is no optimistic update. Wait (auto-retrying) for the row to leave
    // its pre-edit time, so we read the post-edit value rather than racing the
    // pending fetch and comparing two still-equal stale values.
    await expect(rowWhen).not.toHaveAttribute("data-rel", beforeRel || "__never__");
    const rowRel = await rowWhen.getAttribute("data-rel");

    // DESIRED: the banner (same event) now matches the edited row. Today it stays
    // frozen at beforeRel (the gap) so this fails -> test.fail() records the proven
    // gap; the moment a fix re-renders the banner this passes and CI goes red.
    await expect(bannerWhen).toHaveAttribute("data-rel", rowRel || "__never__");
  } finally {
    await ctx.close();
  }
});
