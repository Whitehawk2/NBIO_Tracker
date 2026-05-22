/* NBIO service worker — app shell precache + offline outbox interception.
 *
 * The cache name is templated at response time by routes/sw.py — the
 * `__NBIO_VERSION__` placeholder is replaced with a content-hash of
 * everything under static/. When the shell changes the cache name
 * changes, the `activate` handler below purges the old cache, and the
 * fetch handlers refetch the new shell from the network. (See #23.)
 *
 * Static-asset strategy: **network-first** with cache fallback. The
 * previous cache-first strategy meant an installed PWA could keep
 * serving a stale `app.js` long after a deploy — the new SW would
 * install + claim and activate would purge the old cache, but on the
 * user's first navigation the cache-first handler would still try
 * `caches.match()` first. Combined with the install step having
 * populated the new cache from a possibly-stale browser HTTP cache,
 * a parent on a phone could see yesterday's UI for hours. Symptom
 * observed in the field: the formula chip set didn't update after
 * a deploy until a forced reload. Network-first guarantees fresh
 * shell on every page load when online, with cache only as the
 * offline fallback (its actual job for this PWA).
 */
const CACHE = "nbio-__NBIO_VERSION__";
const SHELL = [
  "/",
  "/static/app.css",
  "/static/app.js",
  "/static/idb.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

function isMutationToEvents(req) {
  if (req.method === "GET" || req.method === "HEAD") return false;
  const url = new URL(req.url);
  return url.pathname.startsWith("/api/events");
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Don't intercept SSE
  if (url.pathname === "/api/stream") return;

  // Mutations: try network; on failure, page-side queue handles it. We do NOT
  // intercept here because the page already runs the optimistic insert + enqueue
  // flow when fetch() rejects. Letting failures propagate to the page is simpler
  // and avoids double-queueing.
  if (isMutationToEvents(req)) return;

  // Network-first for /api/events GET, fall back to cache
  if (req.method === "GET" && url.pathname.startsWith("/api/events")) {
    event.respondWith(
      fetch(req).then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return r;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // Network-first for the shell + static assets. Cache only acts as the
  // offline fallback — when the user is online, every page load picks
  // up the freshly-deployed app.js / app.css / template HTML. Without
  // this, PWAs (especially iOS-installed ones) keep serving stale
  // assets after a deploy because cache-first would short-circuit the
  // network roundtrip.
  if (req.method === "GET" && (url.pathname === "/" || url.pathname.startsWith("/static/"))) {
    event.respondWith(
      fetch(req).then((r) => {
        if (r.ok) {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return r;
      }).catch(() => caches.match(req).then((cached) => cached || caches.match("/")))
    );
    return;
  }
});
