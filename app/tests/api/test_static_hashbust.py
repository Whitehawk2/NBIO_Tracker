"""
v1.2.0 static-asset hash-busting.

Real-user incident: deploying v1.2.0 over a v1.1.x PWA left the
"Both" tile visible (fresh HTML from network-first SW) but inert
(stale `/static/app.js` from the SW cache). The PR-#84 self-heal
only catches the inverse failure mode (stale HTML vs. fresh server)
— it cannot detect fresh-HTML-with-stale-JS, because that's exactly
the state the comparison is run inside.

The durable fix is to bust the script/style URLs with the current
static hash. Each deploy bumps the hash, every cache layer (SW
caches.match, browser HTTP cache, intermediary proxies) misses on
the new URL, and the fetch falls through to the network. The SW
fetch handler uses `ignoreSearch: true` on the offline-fallback
caches.match so the precached bare URL still satisfies a hash-busted
request when offline.

These tests pin: HTML references hash-busted URLs for app.js, idb.js,
settings.js, app.css; the hash matches `nbio.version.static_assets_hash()`;
the sw.js fetch handler uses ignoreSearch on the static caches.match.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nbio.version import static_assets_hash

SW_JS = Path(__file__).resolve().parents[2] / "nbio" / "static" / "sw.js"


@pytest.fixture(scope="module")
def server_hash() -> str:
    return static_assets_hash()


def test_index_hash_busts_app_js(client, server_hash):
    body = client.get("/").text
    expected = f'src="/static/app.js?v={server_hash}"'
    assert expected in body, f"index page must hash-bust app.js src; expected {expected!r} in body"


def test_index_hash_busts_idb_js(client, server_hash):
    body = client.get("/").text
    assert f'src="/static/idb.js?v={server_hash}"' in body, "index page must hash-bust idb.js src"


def test_index_hash_busts_app_css(client, server_hash):
    body = client.get("/").text
    assert f'href="/static/app.css?v={server_hash}"' in body, (
        "index page must hash-bust app.css href"
    )


def test_index_does_not_reference_bare_app_js(client):
    """A bare `src="/static/app.js"` would let an old cache-first SW
    keep serving yesterday's JS. The HTML must always carry the
    `?v=<hash>` suffix so the URL itself changes per deploy."""
    body = client.get("/").text
    # The bare form would appear as src="/static/app.js" with NO
    # `?v=` immediately after; permit only the hash-busted variant.
    assert not re.search(r'src=["\']/static/app\.js["\']', body), (
        'index page must NOT reference bare `src="/static/app.js"` — '
        "the URL must be hash-busted to escape cache-first SW staleness"
    )


def test_settings_page_hash_busts_settings_js(client, server_hash):
    body = client.get("/settings").text
    assert f'src="/static/settings.js?v={server_hash}"' in body, (
        "settings page must hash-bust settings.js src"
    )


def test_settings_page_does_not_reference_bare_settings_js(client):
    body = client.get("/settings").text
    assert not re.search(r'src=["\']/static/settings\.js["\']', body), (
        "settings page must NOT reference bare `/static/settings.js`"
    )


def test_reports_page_hash_busts_app_js(client, server_hash):
    """`/reports` also extends base.html so it gets the same hash-busted
    refs. Pin so a future template change doesn't accidentally regress."""
    body = client.get("/reports").text
    assert f'src="/static/app.js?v={server_hash}"' in body, "reports page must hash-bust app.js src"


# --- SW fetch handler -------------------------------------------------------


def test_sw_fetch_handler_uses_ignore_search_on_static_match():
    """
    Offline scenario after deploy: page requests `/static/app.js?v=NEW`.
    Network is down; SW falls back to `caches.match`. Without
    `ignoreSearch: true` the precached bare `/static/app.js` doesn't
    match the query-busted request and offline silently breaks.
    """
    src = SW_JS.read_text()
    assert "ignoreSearch: true" in src or "ignoreSearch:true" in src, (
        "sw.js fetch handler must pass {ignoreSearch: true} to caches.match "
        "so hash-busted /static/* URLs still resolve to the precached "
        "bare URLs when offline"
    )
