// @ts-check
// AUDIT GAP G4 — the today-card "last feed/wee/poo" cells (today_card.html:23-58
// `[data-last=...]`) are written only server-side; neither insertOrUpdateRow nor
// bumpOverviews touches them, so they stay stale after a log until reload.
// Verified by MCP probe 2026-06-01: a new feed bumped the count 2->3 but the
// "last feed" cell did not move. Fixed in PR-B4.
const { test, expect } = require("@playwright/test");

const LAST_FEED_REL = '#today-card [data-last="feed"] [data-rel]';
const FEED_COUNT = '#today-card [data-count="feed"]';

test("G4: today-card 'last feed' cell updates when a feed is logged", async ({ browser }) => {
  test.fail();
  const ctx = await browser.newContext({ storageState: "playwright/.auth/parent-a.json" });
  const a = await ctx.newPage();
  try {
    await a.goto("/");
    await expect(a.locator("#sync-badge .sync-dot")).toHaveAttribute("data-state", "connected");

    const before = await a.locator(LAST_FEED_REL).getAttribute("data-rel");
    const beforeCount = parseInt(await a.locator(FEED_COUNT).textContent(), 10);

    // Log a formula feed through the proven UI flow (formula counts as a feed).
    await a.locator('.tile[data-type="formula"]').click();
    const modal = a.locator(".modal-sheet");
    await expect(modal).toBeVisible();
    await modal.locator('.seg[data-vol="30"]').click();
    await modal.locator(".btn-primary").click();
    await expect(modal).toBeHidden();

    // The feed COUNT is reactive — sanity that the log actually landed.
    await expect(a.locator(FEED_COUNT)).toHaveText(String(beforeCount + 1));
    // DESIRED: the "last feed" cell now reflects the just-logged (newer) feed.
    await expect(a.locator(LAST_FEED_REL)).not.toHaveAttribute("data-rel", before || "__never__");
  } finally {
    await ctx.close();
  }
});
