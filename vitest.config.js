// Vitest config for NBIO Tracker's JS test harness (issue #63).
//
// Production JS is vanilla, IIFE-wrapped, served as-is from app/nbio/static/
// with no build step. Tests live OUTSIDE static/ at app/nbio/tests_js/ so they
// don't pollute static_assets_hash() (which iterates static/ recursively to
// drive the cache-bust version — see app/nbio/version.py).
//
// jsdom + fake-indexeddb give us a DOM + IndexedDB inside Vitest. The
// setupFiles hook loads fake-indexeddb's auto-shim and then evaluates the
// production idb.js so window.NBIO_IDB is available to every test.

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["app/nbio/tests_js/**/*.test.js"],
    setupFiles: ["app/nbio/tests_js/setup.js"],
    // Report-only coverage for the harness PR. Threshold gate is deferred
    // until the JS suite has meaningful breadth (#81 reactivity router is
    // where the next real tests land).
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["app/nbio/static/**/*.js"],
      exclude: ["app/nbio/static/sw.js"],
    },
  },
});
