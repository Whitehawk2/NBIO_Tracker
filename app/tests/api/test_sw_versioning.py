"""
GET /static/sw.js is templated: the placeholder `__NBIO_VERSION__` in
the source is substituted with the current static-assets hash at
response time. This fixes #23 — installed PWAs no longer keep running
the stale shell after an upgrade, because the cache name changes on
every static-asset change and the existing `activate` handler in sw.js
purges non-matching caches.
"""

import re


def test_sw_js_returns_javascript(client):
    r = client.get("/static/sw.js")
    assert r.status_code == 200
    ct = r.headers["content-type"].lower()
    assert "javascript" in ct


def test_sw_js_substitutes_the_version_placeholder(client):
    """The literal placeholder must not appear in the served body."""
    r = client.get("/static/sw.js")
    assert "__NBIO_VERSION__" not in r.text


def test_sw_js_cache_name_includes_the_hash(client):
    """The cache name `nbio-<hash>` is what makes the SW pick up updates."""
    from nbio.version import static_assets_hash

    expected = static_assets_hash()
    r = client.get("/static/sw.js")
    # Pattern: `const CACHE = "nbio-<hash>";` somewhere in the file
    assert re.search(rf'CACHE\s*=\s*"nbio-{expected}"', r.text), (
        f"sw.js does not contain expected cache name 'nbio-{expected}':\n{r.text[:300]}"
    )


def test_sw_js_response_is_not_cached_by_the_browser(client):
    """
    Browsers honour Cache-Control: no-cache for the SW resource and
    revalidate every fetch. Without this, an updated SW could be ignored
    for up to 24h (the browser default for SW revalidation).
    """
    r = client.get("/static/sw.js")
    cache_control = r.headers.get("cache-control", "").lower()
    assert "no-cache" in cache_control or "no-store" in cache_control, (
        f"sw.js must opt out of HTTP caching; got Cache-Control: {cache_control!r}"
    )


def test_sw_js_route_wins_over_staticfiles_mount(client):
    """
    The route should take precedence over `app.mount("/static", ...)`
    so the substitution happens — otherwise the raw placeholder would
    leak. This test is implicit in test_sw_js_substitutes_the_version_
    placeholder above, but pin it explicitly for the contract.
    """
    raw_source = (__import__("nbio.main", fromlist=["STATIC_DIR"]).STATIC_DIR / "sw.js").read_text()
    assert "__NBIO_VERSION__" in raw_source, (
        "test invariant: sw.js source must contain the placeholder"
    )
    r = client.get("/static/sw.js")
    # Substituted body, not the raw source
    assert r.text != raw_source
    assert "__NBIO_VERSION__" not in r.text


def test_sw_install_calls_skip_waiting(client):
    """
    The SW must call `skipWaiting()` so a new version doesn't wait for
    all open tabs to close before activating. Without this, on a
    re-deploy with a new static-asset hash, users would keep seeing the
    OLD CSS until they fully closed and reopened the PWA — which on
    Android Chrome means the new HTML (network-fetched) and the old CSS
    (cached by the still-active old SW) co-exist and produce visual
    regressions (see v1.0.1 → v1.1.0 production feedback).
    """
    r = client.get("/static/sw.js")
    assert "self.skipWaiting()" in r.text, (
        "sw.js install handler must call self.skipWaiting() so the new "
        "SW activates immediately on next page visit, not after all tabs close"
    )


def test_sw_activate_claims_clients(client):
    """
    Symmetric to skipWaiting: the activate handler must call
    `clients.claim()` so the newly-activated SW takes control of any
    already-open tab. Without it, a freshly-installed SW will only
    control the NEXT navigation, leaving the current page on the old
    SW until the user manually reloads.
    """
    r = client.get("/static/sw.js")
    assert "clients.claim()" in r.text, (
        "sw.js activate handler must call self.clients.claim() so the "
        "new SW takes over the open tab"
    )


def test_sw_static_assets_use_network_first(client):
    """
    Static assets (`/static/*` and `/`) MUST use a network-first fetch
    strategy with cache as the offline fallback — NOT cache-first.

    Why: cache-first lets a stale `app.js` persist in an installed PWA
    even after a deploy. Symptom observed in the field: the formula
    chip set in app.js was updated + deployed, but the PWA kept
    showing the old chips because cache-first short-circuited the
    network roundtrip. Network-first guarantees the user picks up the
    fresh shell on the next page load when online; cache still acts
    as the offline fallback (its actual job for this PWA).

    Pin the contract: the fetch handler for /static/* must call
    `fetch(req)` BEFORE `caches.match(req)` — i.e. cache is the
    `.catch()` branch, not the first branch.
    """
    r = client.get("/static/sw.js")
    body = r.text
    # Find the fetch-handler block that targets /static/. Pull a slice
    # large enough to contain its body.
    idx = body.find('url.pathname.startsWith("/static/")')
    assert idx >= 0, "expected a fetch handler branch targeting /static/* in sw.js"
    # The handler body extends until the next closing `return;` at the same
    # indent — grab a generous window.
    block = body[idx : idx + 800]
    # In network-first form, `fetch(req)` is the first call inside
    # event.respondWith, and `caches.match(req)` only appears inside a
    # `.catch(...)` continuation. Pin both halves:
    assert ".catch(" in block and "caches.match(req)" in block, (
        "static-asset handler must keep a cache.match fallback in its "
        ".catch() so offline still works"
    )
    fetch_pos = block.find("fetch(req)")
    cache_pos = block.find("caches.match(req)")
    assert fetch_pos >= 0, (
        "static-asset handler must call fetch(req) (network-first), not caches.match() first"
    )
    assert fetch_pos < cache_pos, (
        "static-asset handler is cache-first — must be network-first so "
        "deployed updates reach installed PWAs on next reload. "
        f"Found fetch() at offset {fetch_pos}, caches.match() at offset {cache_pos}"
    )
