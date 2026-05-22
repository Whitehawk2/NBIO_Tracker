"""
`GET /reports/print` — pediatrician-handoff PDF (print-stylesheet variant).

Issue #56. Headline feature for v1.1.2 alongside the merged PR #84 SW
self-heal work. The route renders an A4-portrait, paper-styled HTML page
the user opens in Android Chrome → Share → "Save as PDF" (or Print).

These tests pin both the route contract (whitelist on `days`, cache
headers, status codes) and the rendered HTML contract (section markers,
CSS @page declaration, page-break invariants, self-contained discipline).
Regressions in a clinical handoff are silently bad, so the section pins
are deliberately verbose.
"""

from __future__ import annotations

import re

# Distinctive classes on the print page, chosen so they cannot accidentally
# satisfy the existing /reports template tests (which assert on
# `id="totals-body"`, `class="heatmap-grid"`, etc.).
COVER_MARKER = 'class="print-cover"'
NOTES_MARKER = 'class="print-notes"'
TOTALS_TABLE_MARKER = 'class="print-totals"'
TOTALS_ROW_MARKER = 'class="print-day-row"'
TIMELINE_SECTION_MARKER = 'class="print-timeline"'
TIMELINE_STRIP_RE = re.compile(r'<svg[^>]*class="print-timeline-strip"')
WEIGHT_SECTION_MARKER = 'class="print-weight"'
WEIGHT_POLYLINE_RE = re.compile(r'<polyline[^>]*class="print-weight-poly"')


# --- route + headers ---------------------------------------------------------


def test_print_route_returns_html_200_with_default_days(client):
    r = client.get("/reports/print")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"].lower()


def test_print_route_accepts_each_whitelisted_window(client):
    for days in (7, 14, 30):
        r = client.get(f"/reports/print?days={days}")
        assert r.status_code == 200, f"days={days} failed: {r.text}"


def test_print_route_rejects_non_whitelisted_window(client):
    """
    Whitelist `{7, 14, 30}` matches the chip UX on /reports. Anything
    outside that set returns 400 with a helpful body, NOT a 500 or a
    silently-coerced 14.
    """
    for bad in (1, 6, 8, 15, 31, 99, 365):
        r = client.get(f"/reports/print?days={bad}")
        assert r.status_code == 400, f"days={bad} should be 400, got {r.status_code}"
        body = r.text.lower()
        assert "days" in body, f"400 body should explain the days constraint, got: {r.text!r}"


def test_print_route_rejects_negative_and_non_int(client):
    assert client.get("/reports/print?days=-1").status_code in (400, 422)
    assert client.get("/reports/print?days=abc").status_code in (400, 422)


def test_print_response_is_uncached(client):
    """
    A re-print 5 min later must reflect fresh data, not a stale snapshot
    from the browser cache. Pin `Cache-Control: no-cache` (or no-store).
    """
    r = client.get("/reports/print?days=14")
    cache_control = r.headers.get("cache-control", "").lower()
    assert "no-cache" in cache_control or "no-store" in cache_control, (
        f"GET /reports/print must opt out of HTTP caching; got Cache-Control: {cache_control!r}"
    )


# --- format pins (CSS / page setup) -----------------------------------------


def test_print_page_declares_a4_portrait(client):
    """The @page rule pins the paper format clinicians will print on."""
    body = client.get("/reports/print?days=14").text
    assert "@page" in body, "print page must contain an @page CSS rule"
    assert re.search(r"@page\s*\{[^}]*A4\s+portrait", body, re.IGNORECASE), (
        "print page must pin `size: A4 portrait` in the @page rule"
    )


def test_print_page_pins_no_split_on_timeline_strips(client):
    """
    Each per-day timeline strip must carry `page-break-inside: avoid`
    so a 30-day window never splits a strip across a page boundary.
    """
    body = client.get("/reports/print?days=14").text
    assert "page-break-inside: avoid" in body or "page-break-inside:avoid" in body, (
        "timeline-strip CSS must include `page-break-inside: avoid`"
    )


def test_print_page_is_self_contained(client):
    """
    A misbehaving SW could intercept anything under `/static/*` and
    serve stale bytes. The print page must therefore not reference any
    `/static/*` resource: CSS, JS, fonts, icons, manifest. Same
    discipline as /recover (see tests/api/test_recover.py).
    """
    body = client.get("/reports/print?days=14").text
    asset_refs = re.findall(
        r'(?:href|src|action)\s*=\s*["\']/static/[^"\']+', body, flags=re.IGNORECASE
    )
    assert not asset_refs, (
        "print page loads external resources under /static/* — but a "
        "broken SW can intercept those paths. Inline everything. Found: "
        f"{asset_refs}"
    )


def test_print_page_has_no_app_chrome(client):
    """
    Print page must not inherit base.html's app header / nav / install
    banner. Pin the absence of distinctive chrome classes.
    """
    body = client.get("/reports/print?days=14").text
    forbidden = [
        'class="app-header"',
        'class="bottom-nav"',
        "data-vitd-banner",
        "data-install-banner",
    ]
    for marker in forbidden:
        assert marker not in body, (
            f"print page leaks app chrome ({marker!r}) — it must be a "
            "standalone template that does NOT extend base.html"
        )


# --- cover section -----------------------------------------------------------


def test_cover_section_present_with_baby_info(client):
    """Cover header carries baby name, age placeholder, date range, generated-at."""
    body = client.get("/reports/print?days=14").text
    assert COVER_MARKER in body, "print page must contain a `.print-cover` section"
    # Seeded baby name from conftest:
    assert "Test Baby" in body, "cover must include the baby name from repo.baby()"


def test_cover_shows_selected_window_label(client):
    """The selected days window must be reflected in the cover for each preset."""
    for days in (7, 14, 30):
        body = client.get(f"/reports/print?days={days}").text
        # We render "Last 7 days" / "Last 14 days" / "Last 30 days" somewhere
        # in the cover. Loose match: the number + the word "days" close together.
        assert re.search(rf"\b{days}\s*day", body, flags=re.IGNORECASE), (
            f"cover for days={days} must mention `{days} days`"
        )


def test_title_includes_baby_name(client):
    """
    `<title>` drives the browser print dialog's default filename. Should
    carry the baby name so saved PDFs are named usefully.
    """
    body = client.get("/reports/print?days=14").text
    m = re.search(r"<title>([^<]+)</title>", body)
    assert m, "print page must have a <title>"
    title = m.group(1)
    assert "Test Baby" in title, f"<title> must include the baby name; got {title!r}"


# --- daily totals section ----------------------------------------------------


def test_daily_totals_table_present(client):
    body = client.get("/reports/print?days=14").text
    assert TOTALS_TABLE_MARKER in body, "print page must contain a `.print-totals` table"


def test_daily_totals_row_count_matches_window(client, freezer):
    """
    The table must have exactly N rows (one per local day in the window),
    padded for days with zero events. Reuses the `_last_days_rows` pad
    helper that the live /reports page already uses for the 14-day strip.
    """
    freezer.move_to("2026-05-22T12:00:00Z")
    for days in (7, 14, 30):
        body = client.get(f"/reports/print?days={days}").text
        rows = re.findall(TOTALS_ROW_MARKER, body)
        assert len(rows) == days, f"days={days}: expected {days} daily-totals rows, got {len(rows)}"


def test_daily_totals_includes_seeded_event_counts(client, freezer):
    """
    Seed a feed event today; the totals row for today must reflect a
    non-zero feed count (data is actually flowing through the route).
    """
    freezer.move_to("2026-05-22T12:00:00Z")
    r = client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": "2026-05-22T10:00:00.000Z",
            "feed_side": "L",
            "feed_duration_min": 12,
            "idempotency_key": "idem-pr-feed-1",
            "created_by_device": "device-test",
        },
    )
    assert r.status_code in (200, 201), r.text
    body = client.get("/reports/print?days=7").text
    # Today's row should contain a "1" for feed count. We don't pin the
    # exact column layout; just confirm a 1 appears in the table area.
    table_match = re.search(r'<table[^>]*class="print-totals"[^>]*>(.+?)</table>', body, re.DOTALL)
    assert table_match, "could not locate the print-totals table in the response"
    table_html = table_match.group(1)
    assert ">1<" in table_html or " 1 " in table_html, (
        "today's row in the print-totals table should show a non-zero feed count"
    )


# --- timeline strips section -------------------------------------------------


def test_timeline_section_has_one_strip_per_day(client, freezer):
    freezer.move_to("2026-05-22T12:00:00Z")
    for days in (7, 14, 30):
        body = client.get(f"/reports/print?days={days}").text
        assert TIMELINE_SECTION_MARKER in body, (
            f"days={days}: print page must contain a `.print-timeline` section"
        )
        strips = TIMELINE_STRIP_RE.findall(body)
        assert len(strips) == days, (
            f"days={days}: expected {days} timeline strips, got {len(strips)}"
        )


# --- weight section ----------------------------------------------------------


def test_weight_section_renders_polyline_when_growth_data_exists(client):
    """Posting a couple of weights makes the weight polyline appear."""
    for measured_at, weight_g, idem in (
        ("2026-05-15", 3500, "idem-pr-w-1"),
        ("2026-05-20", 3700, "idem-pr-w-2"),
    ):
        r = client.post(
            "/api/growth",
            json={
                "measured_at": measured_at,
                "weight_g": weight_g,
                "idempotency_key": idem,
                "created_by_device": "device-test",
            },
        )
        assert r.status_code in (200, 201), r.text
    body = client.get("/reports/print?days=14").text
    assert WEIGHT_SECTION_MARKER in body, "print page must contain a `.print-weight` section"
    assert WEIGHT_POLYLINE_RE.search(body), (
        "weight-section must render a `<polyline class='print-weight-poly'>` "
        "when growth_list() is non-empty"
    )


def test_weight_section_handles_empty_growth(client):
    """
    With no growth rows, the weight section MUST still be present (so
    the layout is consistent) but contains an empty-state notice, NOT
    a polyline (which would render as a broken element).
    """
    body = client.get("/reports/print?days=14").text
    assert WEIGHT_SECTION_MARKER in body, "weight section must be present even with no growth data"
    assert not WEIGHT_POLYLINE_RE.search(body), (
        "empty growth list must NOT render a weight polyline"
    )


# --- notes section -----------------------------------------------------------


def test_notes_section_omitted_when_notes_empty(client):
    """Fresh DB → notes_md is empty/null → notes section must NOT render."""
    body = client.get("/reports/print?days=14").text
    assert NOTES_MARKER not in body, (
        "notes section must be hidden entirely when settings.notes_md is empty"
    )


def test_notes_section_renders_when_notes_set(client):
    """After PATCH /api/settings with notes_md, the notes section appears."""
    r = client.patch(
        "/api/settings",
        json={"notes_md": "Baby started sleeping 4h stretches on May 18."},
    )
    assert r.status_code in (200, 204), r.text
    body = client.get("/reports/print?days=14").text
    assert NOTES_MARKER in body, "notes section must render when settings.notes_md is set"
    assert "Baby started sleeping 4h stretches" in body, (
        "notes section must include the literal notes_md text"
    )


# --- reports.html chip wiring ------------------------------------------------


def test_reports_page_links_to_print_for_each_preset(client):
    """
    The trigger UI lives on /reports as three `<a>` chips, one per
    preset, opening in a new tab. Pin all three hrefs.
    """
    body = client.get("/reports").text
    for days in (7, 14, 30):
        href = f'href="/reports/print?days={days}"'
        assert href in body, f"/reports must link to {href}"
    # And the links must open in a new tab so the user keeps /reports.
    assert 'target="_blank"' in body, (
        '/reports print chips must use target="_blank" so the print page opens in a new tab'
    )
