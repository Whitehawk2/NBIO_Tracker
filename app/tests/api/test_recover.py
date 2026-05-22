"""
`GET /recover` is the stuck-PWA escape hatch.

When an installed PWA is wedged on an older code path that the normal
SW lifecycle can't dislodge (field-observed once: pre-PR-#83 cache-
first SW + Chrome HTTP cache combo), the user navigates to /recover
in any browser context and clicks one button. The page unregisters
every service worker and clears Cache Storage, then reloads. IndexedDB
is intentionally NOT touched, so the outbox of unsynced events
survives.

These tests pin the contract end-to-end. They're paranoid by design:
a regression in `recover.html` that accidentally touches IndexedDB
would silently lose unsynced events for any future stuck-PWA user.
"""


def test_recover_route_returns_html_200(client):
    r = client.get("/recover")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"].lower()


def test_recover_response_is_not_cacheable(client):
    """
    A cached copy of the recovery page would defeat its own purpose.
    Pin `Cache-Control: no-store` (or `no-cache`) on the response.
    """
    r = client.get("/recover")
    cache_control = r.headers.get("cache-control", "").lower()
    assert "no-store" in cache_control or "no-cache" in cache_control, (
        f"GET /recover must opt out of HTTP caching; got Cache-Control: {cache_control!r}"
    )


def test_recover_page_unregisters_service_workers(client):
    """
    The page MUST call `getRegistrations()` + `r.unregister()` on each.
    A page that only clears caches would leave the broken SW in charge.
    """
    body = client.get("/recover").text
    assert "navigator.serviceWorker.getRegistrations()" in body, (
        "recovery page must enumerate registrations via getRegistrations()"
    )
    assert ".unregister()" in body, "recovery page must call .unregister() on each registration"


def test_recover_page_clears_cache_storage(client):
    """
    The page MUST iterate caches.keys() and caches.delete() each one.
    Leaving stale Cache Storage entries would mean the new SW (when it
    reinstalls) starts from a poisoned cache.
    """
    body = client.get("/recover").text
    assert "caches.keys()" in body, "recovery page must enumerate Cache Storage via caches.keys()"
    assert "caches.delete(" in body, "recovery page must call caches.delete() on each cache"


def test_recover_page_does_not_touch_indexeddb(client):
    """
    Hardest invariant: the recovery page must NEVER touch IndexedDB —
    that's where the outbox of unsynced events lives. A regression that
    adds an indexedDB.deleteDatabase() call would silently destroy the
    user's queued data on every recovery.

    Pin the absence of every API surface that can mutate or delete IDB.
    """
    body = client.get("/recover").text
    # The truly destructive APIs the page must NEVER call:
    must_not_have = ["indexedDB.deleteDatabase", "deleteDatabase("]
    for needle in must_not_have:
        assert needle not in body, (
            f"recovery page must not contain {needle!r} — that would destroy "
            f"the IndexedDB outbox of unsynced events. The whole point of "
            f"/recover is to preserve queued data."
        )
    # And no mention of `indexedDB` at all — defence in depth.
    assert "indexedDB" not in body, (
        "recovery page references `indexedDB` somewhere — it should not. "
        "The page must only touch ServiceWorker registrations + Cache Storage."
    )


def test_recover_page_is_self_contained(client):
    """
    A misbehaving SW could intercept anything under `/static/*` and
    serve stale bytes — including a stylesheet or JS the recovery page
    depends on. The page must therefore not reference any `/static/*`
    resource: CSS, JS, fonts, icons, manifest. Everything must be
    inlined into the HTML response.

    Pin actual asset references (in href / src attributes) rather than
    raw text matches, so a comment mentioning "/static/*" doesn't
    false-positive.
    """
    import re

    body = client.get("/recover").text
    # Any HTML attribute that loads an external resource pointing under /static/
    asset_refs = re.findall(
        r'(?:href|src|action)\s*=\s*["\']/static/[^"\']+', body, flags=re.IGNORECASE
    )
    assert not asset_refs, (
        "recovery page loads external resource(s) under /static/* — but a "
        "broken SW can intercept those paths. Inline everything. Found: "
        f"{asset_refs}"
    )


def test_recover_page_reloads_to_root_after_clearing(client):
    """
    After the unregister + clear sweep, the page MUST navigate back to
    `/` so the user sees a fresh, SW-uncontrolled boot. Without this
    they'd be left on /recover with an empty caches state, confused.
    """
    body = client.get("/recover").text
    assert "window.location.replace" in body or "location.replace" in body, (
        "recovery page must call location.replace() to navigate to / after "
        "the cleanup, on the same tab and bypassing history"
    )
    # The destination should be `/` (the app root), not /recover itself.
    assert '"/' in body, "recovery page must redirect to `/` after cleanup"


def test_recover_page_is_not_intercepted_by_sw(client):
    """
    Defence in depth: the served `sw.js` must NOT contain a fetch
    handler branch that intercepts /recover. Both the old (cache-first)
    and new (network-first) SW match `/` and `/static/*` only, so this
    should hold trivially — but pin the contract so a future SW change
    that intercepts everything doesn't break the recovery flow.
    """
    sw = client.get("/static/sw.js").text
    assert "/recover" not in sw, (
        "sw.js mentions /recover — if any fetch handler intercepts the "
        "recovery route, a broken SW could serve a stale recovery page "
        "and break the escape hatch."
    )
