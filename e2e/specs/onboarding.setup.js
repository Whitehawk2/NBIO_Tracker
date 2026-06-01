// @ts-check
// The "login" of this app: first-run device onboarding. Real users pick a name
// + colour the first time they open the PWA; until they do, init blocks on the
// "Whose phone is this?" modal (app.js:2140 `await ensureOnboarded()`) and SSE
// never connects. This SETUP project drives that real flow for two parents and
// saves each one's storage state, which every spec below reuses so it starts as
// an already-onboarded device — the steady state real two-parent use runs in.
//
// It is also a genuine test of onboarding: it asserts the modal appears and that
// a name + colour produce a persisted device identity (id + colour in
// localStorage). The server-side /api/devices PUT is fire-and-forget (app.js:80),
// so this asserts local persistence, not server-side registration.

const { test, expect } = require("@playwright/test");

const PARENTS = [
  { name: "Mum", swatch: 0, state: "playwright/.auth/parent-a.json" },
  { name: "Dad", swatch: 2, state: "playwright/.auth/parent-b.json" },
];

for (const p of PARENTS) {
  test(`onboard ${p.name}`, async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto("/");

    // First run: the onboarding sheet blocks the app until a colour is chosen.
    const modal = page.locator(".modal-sheet");
    await expect(modal).toBeVisible();
    await expect(modal.locator(".modal-title")).toHaveText(/whose phone is this/i);

    await modal.locator('input[type="text"]').fill(p.name);
    await modal.locator(".chip").nth(p.swatch).click();
    await modal.getByRole("button", { name: /^save$/i }).click();

    // Saved => sheet dismissed and a persisted local identity (device id + colour).
    await expect(modal).toBeHidden();
    const id = await page.evaluate(() => localStorage.getItem("nbio.device_id"));
    const color = await page.evaluate(() => localStorage.getItem("nbio.device_color"));
    expect(id).toBeTruthy();
    expect(color).toBeTruthy();

    await ctx.storageState({ path: p.state });
    await ctx.close();
  });
}
