// @ts-check
// PR-B5 — offline outbox flush round-trip. The home page had no offline e2e
// coverage (part of #62). Offline, a log goes to the IndexedDB outbox with its
// optimistic count applied; on reconnect flushOutbox POSTs it, the server echoes
// event.created over SSE, and the page must settle to EXACTLY one event — no
// duplicate row, no double count.
//
// This guards the B5 fix wiring (pendingOptimistic add/clear + the pre-fetch
// ownIdems re-key) against gross breakage and exercises the whole offline path
// end to end. NOTE: the SPECIFIC bug B5 targets — a same-session flush >60s after
// enqueue, where ownIdems' 60s TTL (set at log time) has lapsed so the echo
// double-counts — is not reproducible in a fast CI run without a 60s wait or a
// test-only TTL hook. That exact race is pinned structurally in
// app/tests/unit/test_offline_flush_reactivity.py (re-key happens BEFORE the
// POST). Here we prove the end-to-end round-trip stays single.
const { test, expect } = require("@playwright/test");

const FEED_COUNT = '#today-card [data-count="feed"]';

test("B5: an offline-logged feed flushes to exactly one event on reconnect", async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "playwright/.auth/parent-a.json" });
  const a = await ctx.newPage();
  try {
    await a.goto("/");
    await expect(a.locator("#sync-badge .sync-dot")).toHaveAttribute("data-state", "connected");
    const before = parseInt((await a.locator(FEED_COUNT).textContent()) || "0", 10);

    // Go offline, then log a formula feed through the real UI. The POST fails, the
    // event is queued, and the optimistic count bumps to before+1.
    await ctx.setOffline(true);
    await a.locator('.tile[data-type="formula"]').click();
    const modal = a.locator(".modal-sheet");
    await expect(modal).toBeVisible();
    await modal.locator('.seg[data-vol="30"]').click();
    await modal.locator(".btn-primary").click();
    await expect(modal).toBeHidden();
    await expect(a.locator(FEED_COUNT)).toHaveText(String(before + 1)); // optimistic applied
    await expect(a.locator("#sync-pending")).toBeVisible(); // queued-badge shows

    // Reconnect and EXPLICITLY drive the flush trigger (don't wait on the 30s
    // interval). The app's own `online` listener flushes the outbox + reconnects SSE.
    await ctx.setOffline(false);
    await a.evaluate(() => window.dispatchEvent(new Event("online")));

    // Settles to exactly before+1 (no double-count) with the queue drained and the
    // just-logged row reconciled to a real id (no lingering optimistic local: row).
    await expect(a.locator("#sync-pending")).toBeHidden();
    await expect(a.locator(FEED_COUNT)).toHaveText(String(before + 1));
    await expect(a.locator('#event-list li[data-type="formula"]').first()).not.toHaveAttribute("data-pending", "1");
  } finally {
    await ctx.close();
  }
});
