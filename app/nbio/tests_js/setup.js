// Vitest setup file — runs once per test file before any test.
//
// Two jobs:
//
// 1. Install fake-indexeddb so jsdom's missing IndexedDB API resolves to a
//    real (in-memory) implementation that NBIO_IDB can drive.
//
// 2. Evaluate the production app/nbio/static/idb.js into the global jsdom
//    window so window.NBIO_IDB is defined. We use indirect eval (the
//    `(0, eval)` idiom) so the IIFE runs in global scope rather than this
//    setup module's scope — that's what makes `window.NBIO_IDB = …` land
//    on the jsdom window the tests will read.
//
// We deliberately do NOT bundle or transform idb.js. The production code
// path is the source of truth; the test runs the same file the browser
// would. Any future ESM-ification of idb.js can replace this setup with a
// plain `import` without changing the tests themselves.

import "fake-indexeddb/auto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const idbSrc = readFileSync(
  join(__dirname, "..", "static", "idb.js"),
  "utf-8",
);

// Indirect eval: runs in global scope so window.NBIO_IDB lands on jsdom's
// window, not on this module's local scope. Safe here — we control the
// source file (it's checked into the repo, no untrusted input).
// eslint-disable-next-line no-eval
(0, eval)(idbSrc);
