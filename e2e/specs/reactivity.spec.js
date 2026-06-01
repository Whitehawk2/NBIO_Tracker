// @ts-check
// S1 — the proving spec for the E2E harness (issue #94).
//
// Two browser contexts = two parents on the same home page. Parent A logs a
// formula feed through the real UI; we assert:
//   * A updates OPTIMISTICALLY (today formula-cc cell + the "Last 3 days" row),
//   * A does NOT double-count its own SSE echo,
//   * Parent B receives the same delta via SSE.
//
// Assertions are HYDRATION-AWARE: we read the server-rendered cc value (a DB
// aggregate) and assert the DELTA, never an absolute count derived from the
// rows the client happens to hold. See the #94 / #93 design notes.
//
// The bug-reproducing specs (offline-flush, cross-device growth, tz-skew,
// delete double-count) land WITH their fixes in issue #81, not here.

const { test, expect } = require("@playwright/test");

const CC_CELL = '[data-formula-strip] b[data-count="formula_ml"]';
const FORMULA_TILE = '.tile[data-type="formula"]';
const ADD_CC = 30; // a value present in the classic volume chip set

test("formula feed: optimistic on the poster, SSE-delivered to the partner, no double-count", async ({
  browser,
}) => {
  // UTC day == server day (TZ=UTC). The seed (global-setup) and this "today"
  // share a UTC day except if the whole suite straddles UTC midnight between
  // seeding and this spec — a ~seconds window, accepted per the #78 date-fixture
  // rule (now-relative, not a drifting hardcoded date).
  const today = new Date().toISOString().slice(0, 10);
  const rowCcCell = `.last-days-table tr[data-day="${today}"] td[data-col="formula_ml"]`;

  // Two ALREADY-ONBOARDED parents, reusing the storage state saved by the
  // onboarding ("login") setup project: the real first-run name/colour flow runs
  // once there, and every spec builds on its output. This is the steady state
  // two-parent sync runs in — by the time both are logging concurrently, each
  // picked their identity long ago, so init's `await ensureOnboarded()`
  // (app.js:2140) resolves immediately and connectSSE() runs on both tabs.
  const ctxA = await browser.newContext({ storageState: "playwright/.auth/parent-a.json" });
  const ctxB = await browser.newContext({ storageState: "playwright/.auth/parent-b.json" });
  const a = await ctxA.newPage();
  const b = await ctxB.newPage();

  try {
    await a.goto("/");
    await b.goto("/");

    // Hydration-aware baseline: both tabs first-paint from the same aggregate.
    const beforeA = parseInt((await a.locator(CC_CELL).textContent()) || "0", 10);
    const beforeB = parseInt((await b.locator(CC_CELL).textContent()) || "0", 10);
    expect(beforeB).toBe(beforeA);
    expect(beforeA).toBeGreaterThan(0); // the seed (120 cc) is hydrated, not the empty state

    // SSE barrier: the broker only delivers to clients subscribed at publish
    // time, and does NOT replay a live event to a tab that connects later. Init
    // calls connectSSE() late (after `await ensureOnboarded()`), which resolves
    // AFTER goto() returns on `load` — so wait until BOTH tabs report the sync
    // dot "connected" before A posts, or B can miss the echo and flake.
    for (const pg of [a, b]) {
      await expect(pg.locator("#sync-badge .sync-dot")).toHaveAttribute("data-state", "connected");
    }

    // Log ADD_CC through the real formula modal.
    await a.locator(FORMULA_TILE).click();
    const modal = a.locator(".modal-sheet");
    await expect(modal).toBeVisible();
    await modal.locator(`.seg[data-vol="${ADD_CC}"]`).click();
    // The modal's submit button — text is "Save changes" (the tile opens it with
    // a truthy prefill, so the app labels it that even though it still creates),
    // NOT "Save Formula". Match the single primary button, not its text.
    await modal.locator(".btn-primary").click();

    const expected = String(beforeA + ADD_CC);

    // Poster: optimistic update on BOTH surfaces. Exact equality also guards
    // against a double-count (an un-suppressed own-echo would read beforeA + 2*ADD_CC).
    await expect(a.locator(CC_CELL)).toHaveText(expected);
    await expect(a.locator(rowCcCell)).toHaveText(expected);

    // Partner: exactly one delta, delivered over SSE.
    await expect(b.locator(CC_CELL)).toHaveText(expected);
  } finally {
    await ctxA.close();
    await ctxB.close();
  }
});
