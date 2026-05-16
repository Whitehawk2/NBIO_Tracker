/* NBIO service worker — app shell precache + offline outbox interception. */
const CACHE = "nbio-v1";
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

  // Cache-first for shell + static assets
  if (req.method === "GET" && (url.pathname === "/" || url.pathname.startsWith("/static/"))) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((r) => {
        if (r.ok) {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return r;
      }).catch(() => caches.match("/")))
    );
    return;
  }
});
