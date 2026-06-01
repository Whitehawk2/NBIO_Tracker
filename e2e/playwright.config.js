// @ts-check
const { defineConfig } = require("@playwright/test");

// This config runs ONLY inside the Playwright Docker image (the pinned
// mcr.microsoft.com/playwright:v1.60.0-noble, browsers matched to
// @playwright/test@1.60.0). See docker-compose.e2e.yml. The harness is never
// installed on a developer host — dev-time browser checks use the Playwright
// MCP plugin instead.
const BASE_URL = process.env.BASE_URL || "http://localhost:8000";

// Playwright's device registry tops out at Pixel 7; the production fleet is the
// Pixel 9/10 range. This is a Pixel-9-class descriptor (412 CSS-px wide, DPR
// 2.625, Android 15) running the image's bundled Chromium (Chrome 148, so the
// UA stays consistent with the actual engine). Pixel 10 is the same width
// class — add a second project with its UA for explicit matrix coverage.
const pixel9 = {
  userAgent:
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.96 Mobile Safari/537.36",
  viewport: { width: 412, height: 915 },
  screen: { width: 412, height: 923 },
  deviceScaleFactor: 2.625,
  isMobile: true,
  hasTouch: true,
  defaultBrowserType: "chromium",
};

// Pro XL class (Pixel 9 Pro XL / Pixel 10 Pro XL): the larger 6.8" panel —
// ~448 CSS-px wide, DPR 3, on Android 16. Exercises layout/viewport behaviour
// the narrower Pixel 9 won't (tile-grid wrap, chip-row overflow).
const pixel9ProXL = {
  userAgent:
    "Mozilla/5.0 (Linux; Android 16; Pixel 9 Pro XL) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.96 Mobile Safari/537.36",
  viewport: { width: 448, height: 992 },
  screen: { width: 448, height: 997 },
  deviceScaleFactor: 3,
  isMobile: true,
  hasTouch: true,
  defaultBrowserType: "chromium",
};

module.exports = defineConfig({
  testDir: "./specs",
  globalSetup: require.resolve("./global-setup.js"),

  // One app instance backed by one SQLite DB is shared across specs, and the
  // reactivity assertions are count-based. Serialise so a parallel writer can
  // never race another spec's expected counts.
  fullyParallel: false,
  workers: 1,

  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // SSE delivery to the partner tab is near-instant locally but crosses the
  // broker; give cross-tab assertions headroom over the 5s default.
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],

  use: {
    baseURL: BASE_URL,

    // BLOCK the service worker for reactivity specs. The contract under test
    // (optimistic update in submitCreate/bumpOverviews + SSE fan-out in
    // connectSSE) is entirely SW-independent: sw.js bails on /api/stream and on
    // POST mutations. Leaving the SW live lets activate()'s clients.claim() fire
    // controllerchange -> checkVersionAndMaybeReload() -> location.reload() mid-
    // test, tearing down the DOM + EventSource we just asserted on. A dedicated
    // SW/offline/deploy smoke can re-enable it (serviceWorkers: "allow").
    serviceWorkers: "block",

    // The app runs TZ=UTC (which sets both the process tz and settings.tz), so
    // server-bucketed days == browser-bucketed days. Pin the browser tz to UTC
    // to match, keeping the "Last 3 days" data-day keys aligned. The deliberate
    // tz-skew regression lives in a later spec (issue #81), set per-test there.
    timezoneId: "UTC",

    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      // The app's "login": the first-run device-onboarding flow. Runs once and
      // saves each parent's storage state (playwright/.auth/*.json) for the
      // device projects to reuse. testMatch scopes it to the .setup file; the
      // *.spec.js suites are excluded from it by the default test glob.
      name: "setup",
      testMatch: /onboarding\.setup\.js/,
    },
    {
      // Android Chrome is the production primary surface (Pixel 9/10 fleet).
      name: "android-pixel9",
      use: { ...pixel9 },
      dependencies: ["setup"],
    },
    {
      // Larger Pro XL panel + Android 16, for viewport/layout coverage.
      name: "android-pixel9-pro-xl",
      use: { ...pixel9ProXL },
      dependencies: ["setup"],
    },
  ],
});
