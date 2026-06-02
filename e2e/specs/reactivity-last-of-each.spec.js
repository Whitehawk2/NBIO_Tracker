// @ts-check
// AUDIT GAP G4 (FIXED in PR-B4) — the today-card "last feed/wee/poo" cells
// (today_card.html [data-last=...]) were written only at server first-paint;
// neither insertOrUpdateRow nor bumpOverviews touched them, so they stayed stale
// after a log until reload (MCP probe 2026-06-01: a new feed bumped the count
// 2->3 but the "last feed" cell did not move). PR-B4 registers a last-of-each
// updater into the applyEvent seam that re-renders the cell when an incoming
// event is at least as recent as the one shown.
//
// UPSERT-ONLY by design: delete-recompute of the displayed-last is deferred to
// #93's event store (the all-time previous event can be older than the event-
// list's ~2-day window, so there's no client-side source to recompute from).
//
// The proof is HOUR-OF-DAY INDEPENDENT. The UI clamps a log to <= now, so a
// "now" feed can't out-time a seed stamped later today (the latest seed feed is
// formula@12:00 UTC). Instead we post — as the other parent, so it reaches this
// tab purely over SSE — a feed stamped strictly AFTER the current latest feed,
// then assert the cell converges to THAT event, matched on the freshly-inserted
// row's own delivered occurred_at (not a weak "value differs" existence check,
// which could pass while the cell shows the wrong event).
const { test, expect } = require("@playwright/test");

const LAST_FEED_REL = '#today-card [data-last="feed"] [data-rel]';

// `iso` (today, UTC) shifted +mins minutes, as an ISO string. Mints an occurred_at
// strictly newer than the current latest feed so the proof never races wall-clock.
function isoPlusMinutes(iso, mins) {
  return new Date(new Date(iso).getTime() + mins * 60000).toISOString();
}

test("G4: today-card 'last feed' cell updates live when a newer feed is logged", async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "playwright/.auth/parent-a.json" });
  const a = await ctx.newPage();
  try {
    await a.goto("/");
    await expect(a.locator("#sync-badge .sync-dot")).toHaveAttribute("data-state", "connected");

    await expect(a.locator(LAST_FEED_REL)).toBeVisible();
    const before = await a.locator(LAST_FEED_REL).getAttribute("data-rel");
    expect(before, "a seeded last-feed exists at first paint").toBeTruthy();

    // A feed (formula counts as a feed) stamped one minute after the current
    // latest feed — guaranteed to be the new latest at any runtime hour.
    const next = isoPlusMinutes(before, 1);
    const idem = `g4-${next}-${Date.now()}`;
    const r = await ctx.request.post("/api/events", {
      data: {
        type: "formula",
        formula_volume_ml: 30,
        occurred_at: next,
        idempotency_key: idem,
        created_by_device: "e2e-parent-a",
      },
    });
    expect(r.ok(), "feed POST landed").toBeTruthy();

    // The event reaches this tab over SSE and the seam inserts its row. Read the
    // row's OWN delivered occurred_at so the assertion can't drift on any server
    // timestamp normalisation.
    const newRow = a.locator(`#event-list li[data-idem="${idem}"]`);
    await expect(newRow).toBeVisible();
    const newRel = await newRow.locator("[data-rel]").getAttribute("data-rel");
    expect(newRel, "the new feed row carries a relative-time stamp").toBeTruthy();
    expect(newRel).not.toBe(before); // genuinely newer than the prior last-feed

    // DESIRED (G4): the header "last feed" cell now shows that exact event.
    await expect(a.locator(LAST_FEED_REL)).toHaveAttribute("data-rel", newRel);
  } finally {
    await ctx.close();
  }
});
