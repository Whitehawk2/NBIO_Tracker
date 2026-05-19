"""
HTML page renders: GET / and GET /reports → 200 + verification that the
*right* template rendered with the *right* data.

The original looser version (PR #16) only asserted status_code == 200,
which would pass for a tracebacked HTML body or the wrong template. The
review (issue #21, critical gap 2) flagged it; this rewrite anchors on
distinct markup per template plus on data-dependent values.
"""

from datetime import UTC, datetime


def _payload(**over):
    base = {
        "type": "breast",
        "occurred_at": "2026-05-16T03:00:00.000Z",
        "feed_side": "L",
        "feed_duration_min": 15,
        "idempotency_key": "idem-pages-aa",
        "created_by_device": "device-test",
    }
    base.update(over)
    return base


# Distinct markers that exist on exactly one of the two pages — chosen
# from the rendered HTML so the test fails loudly if the route returns
# the wrong template.
INDEX_ONLY_MARKERS = (
    'class="tiles"',  # tiles section is on /
    'href="/" class="nav-item active"',  # Home nav is active on /
)
REPORTS_ONLY_MARKERS = (
    'id="totals-body"',  # totals table tbody
    'id="copy-summary"',  # "Copy as text" button
    'class="heatmap-grid"',  # heatmap container
    'href="/reports" class="nav-item active"',
)


def _assert_is_index(html: str) -> None:
    for marker in INDEX_ONLY_MARKERS:
        assert marker in html, f"index page missing marker: {marker!r}"
    for marker in REPORTS_ONLY_MARKERS:
        assert marker not in html, f"index page contains reports-only marker: {marker!r}"


def _assert_is_reports(html: str) -> None:
    for marker in REPORTS_ONLY_MARKERS:
        assert marker in html, f"reports page missing marker: {marker!r}"
    for marker in INDEX_ONLY_MARKERS:
        assert marker not in html, f"reports page contains index-only marker: {marker!r}"


def test_index_shows_vitd_banner_not_given_state(client):
    """Fresh DB → banner reads 'Vitamin D — not yet' with a Give now button."""
    r = client.get("/")
    assert r.status_code == 200
    assert "data-vitd-banner" in r.text
    assert "not yet" in r.text or "not given" in r.text.lower()
    assert "data-vitd-give" in r.text  # Give now button


def test_index_shows_vitd_banner_given_state_after_post(client):
    """After a vit D event today, banner flips to the given state."""
    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "vitd",
            "occurred_at": f"{today}T09:00:00.000Z",
            "idempotency_key": "idem-vitd-banner",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "data-vitd-banner" in r.text
    assert "is-given" in r.text
    # The Give now button is gone in the given state.
    assert "data-vitd-give" not in r.text


def test_index_shows_tummy_banner_empty_state(client):
    """Fresh DB → tummy banner reads 'Tummy time — not yet today' + buttons."""
    r = client.get("/")
    assert r.status_code == 200
    assert "data-tummy-banner" in r.text
    assert "not yet" in r.text.lower()
    assert "data-tummy-log" in r.text  # quick-log button
    assert "data-tummy-start" in r.text  # start-timer button


def test_index_shows_tummy_banner_done_state_after_post(client):
    """After a tummy_time event today, banner flips to the given state."""
    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "tummy_time",
            "occurred_at": f"{today}T08:00:00.000Z",
            "feed_duration_min": 5,
            "idempotency_key": "idem-tummy-banner",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "data-tummy-banner" in r.text
    assert "is-given" in r.text
    # Session count + minutes total surface in the banner text.
    assert "Tummy today" in r.text
    # The Start-timer button is hidden in the done state (replaced with Add another).
    assert "data-tummy-start" not in r.text


def test_event_row_renders_tummy_emoji(client):
    """An event of type='tummy_time' shows the 🤸 emoji in its row."""
    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "tummy_time",
            "occurred_at": f"{today}T08:00:00.000Z",
            "feed_duration_min": 5,
            "idempotency_key": "idem-tummy-emoji",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "🤸" in r.text


def test_event_row_renders_vitd_emoji(client):
    """An event of type='vitd' shows the 💊 emoji in its row."""
    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "vitd",
            "occurred_at": f"{today}T09:00:00.000Z",
            "idempotency_key": "idem-vitd-emoji",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    # The row's emoji span carries 💊 for vitd type.
    import re

    m = re.search(
        r'<li class="event-row"[^>]*data-type="vitd"[^>]*>(.*?)</li>',
        r.text,
        flags=re.DOTALL,
    )
    assert m, "vitd event row not found"
    assert "💊" in m.group(1), "vitd row must render the 💊 emoji"


def test_index_renders_index_template(client):
    """A fresh client → / returns the index template (not reports)."""
    r = client.get("/")
    assert r.status_code == 200
    _assert_is_index(r.text)


def test_reports_renders_reports_template(client):
    """And / and /reports return DIFFERENT templates."""
    r = client.get("/reports")
    assert r.status_code == 200
    _assert_is_reports(r.text)


def test_index_baby_name_in_header(client):
    """The seeded baby name from conftest appears in the header."""
    r = client.get("/")
    assert "Test Baby" in r.text


def test_settings_page_renders(client):
    """GET /settings → 200, distinct marker id='settings-page'."""
    r = client.get("/settings")
    assert r.status_code == 200
    assert 'id="settings-page"' in r.text


def test_settings_baby_section_includes_weight_subsection_empty(client):
    """Fresh DB → Baby section has 'No weights recorded yet.'"""
    r = client.get("/settings")
    assert r.status_code == 200
    assert "data-weight-empty" in r.text
    assert "Record first weight" in r.text


def test_settings_baby_section_includes_weight_subsection_populated(client):
    """After one growth row, settings shows the latest line + 'Update weight'."""
    client.post(
        "/api/growth",
        json={
            "measured_at": "2026-05-16",
            "weight_g": 3420,
            "idempotency_key": "idem-settings-weight",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/settings")
    assert r.status_code == 200
    assert "data-weight-latest" in r.text
    assert "3,420 g" in r.text
    assert "Update weight" in r.text


def test_settings_page_has_five_sections(client):
    """Five `<details>` tabs: Baby / This device / Display / Data / System."""
    r = client.get("/settings")
    assert r.status_code == 200
    for label in ("Baby", "This device", "Display", "Data", "System"):
        assert f">{label}</summary>" in r.text, f"missing settings tab: {label}"
    # Five `<details>` elements total, all in the same exclusive-open group.
    assert r.text.count('<details name="settings-tab"') == 5


def test_settings_display_has_three_theme_cards(client):
    """Display section shows three theme cards: warm, latte, mocha."""
    r = client.get("/settings")
    assert r.status_code == 200
    for value in ("warm", "latte", "mocha"):
        assert f'data-theme-value="{value}"' in r.text, f"missing theme card for theme={value!r}"
    # Exactly three (not more, not fewer).
    assert r.text.count("data-theme-value=") == 3


def test_theme_cards_have_palette_preview_swatches(client):
    """
    Each theme card shows a 5-swatch preview row (bg / accent / feed /
    poo / vitd) so the user can scan the palette before tapping.
    """
    r = client.get("/settings")
    assert r.status_code == 200
    import re

    cards = re.findall(
        r'<button[^>]+data-theme-value="(warm|latte|mocha)"[^>]*>(.*?)</button>',
        r.text,
        flags=re.DOTALL,
    )
    assert len(cards) == 3
    for theme, inner in cards:
        assert 'class="theme-preview"' in inner, (
            f"{theme} card must contain a `.theme-preview` swatch row"
        )
        # Five swatch <span> elements inside the preview row.
        preview_m = re.search(
            r'<span class="theme-preview"[^>]*>(.*?)</span>\s*</button>',
            inner + "</button>",
            flags=re.DOTALL,
        )
        assert preview_m, f"{theme} preview row not parseable"
        swatch_count = preview_m.group(1).count("<span")
        assert swatch_count == 5, (
            f"{theme} preview must have 5 swatches (bg/accent/feed/poo/vitd); got {swatch_count}"
        )


def test_bottom_nav_has_three_columns(client):
    """A new Settings link sits next to Home + Reports in the bottom nav."""
    r = client.get("/")
    assert r.status_code == 200
    # The Settings nav item.
    assert 'href="/settings"' in r.text
    assert 'aria-label="Settings"' in r.text


def test_header_shows_baby_age_when_dob_set(client):
    """After setting dob, the header carries a `data-baby-age` span."""
    client.patch("/api/babies", json={"dob": "2026-04-20"})
    r = client.get("/")
    assert r.status_code == 200
    import re

    # Age span carries a `data-baby-age` attribute + a `data-dob` for
    # client-side recompute (handled by app.js, tested separately).
    m = re.search(r"<span[^>]*data-baby-age[^>]*>([^<]+)</span>", r.text)
    assert m, "expected `<span data-baby-age>` in header after dob set"
    # Age string format: digits + d/w/m/y, e.g. "4w 2d" or "12d".
    assert re.search(r"\d+\s*[dwmy]", m.group(1))


def test_header_omits_age_when_dob_unset(client):
    """No `data-baby-age` span if dob is null (the default)."""
    r = client.get("/")
    assert r.status_code == 200
    assert "data-baby-age" not in r.text


def test_index_shows_event_in_grouped_list(client):
    """An event posted via the API appears in the grouped event list."""
    # Use today's date so the event lands inside the home page's
    # last-3-days filter window — a hardcoded 2026-05-16 here drifts
    # past the window once wall-clock now is >2 days later.
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json=_payload(idempotency_key="idem-index-1", occurred_at=f"{today}T03:00:00.000Z"),
    )
    r = client.get("/")
    assert r.status_code == 200
    _assert_is_index(r.text)
    # Event row markup is `<li class="event-row" data-id="..." data-idem="...">`
    assert 'class="event-row"' in r.text
    assert 'data-idem="idem-index-1"' in r.text


def test_index_with_known_device_renders_actor_color(client):
    """If a device is upserted first, its color appears as the actor swatch."""
    client.put(
        "/api/devices/device-test",
        json={"name": "Mum", "color": "#4f8bff"},
    )
    client.post("/api/events", json=_payload(idempotency_key="idem-index-color"))
    r = client.get("/")
    assert r.status_code == 200
    # event_row.html: `style="background: {{ event.actor_color or '#888' }}"`
    assert "background: #4f8bff" in r.text or "background: #4F8BFF" in r.text
    assert 'title="Mum"' in r.text


def test_reports_today_counts_render_in_big_numbers(client):
    """today.counts.feed renders inside the .big-numbers block."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for i in range(3):
        client.post(
            "/api/events",
            json=_payload(
                idempotency_key=f"idem-rpts-cnt-{i:04d}",
                occurred_at=f"{today}T{i:02d}:00:00.000Z",
            ),
        )
    r = client.get("/reports")
    assert r.status_code == 200
    _assert_is_reports(r.text)
    # 3 feeds today, 0 wees, 0 poos — assert the counts appear inside .big-numbers
    big_block_start = r.text.find('class="big-numbers"')
    assert big_block_start != -1
    big_block_end = r.text.find("</div>", big_block_start)
    big_block = r.text[big_block_start : big_block_end + len("</div>")]
    assert "<b>3</b>" in big_block
    # The "feeds" label should be the one paired with 3
    assert "feeds" in big_block


# ---------------------------------------------------------------------------
# Reactive overview refresh (issue #28 #2) — these tests pin the stable
# `data-*` selectors that app.js::bumpOverviews depends on. The actual
# DOM-mutation behaviour isn't unit-testable without a browser harness;
# Pi-side manual verification covers that.
# ---------------------------------------------------------------------------


def test_event_row_exposes_formula_volume_ml_data_attr(client):
    """
    Server-rendered event rows must expose `formula_volume_ml` as a
    `data-` attribute so JS `wireExistingRows` can hydrate it into
    `row.__event` for the reactive-refresh path.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T03:00:00.000Z",
            "formula_brand": "Materna",
            "formula_volume_ml": 240,
            "idempotency_key": "idem-row-data-attr-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    import re

    assert re.search(r'data-formula-volume-ml="240"', r.text), (
        "formula rows must carry data-formula-volume-ml='<n>' so JS can "
        "hydrate __event for reactive cc updates on deletion"
    )


def test_tile_hint_rendered_outside_tile_button(client):
    """
    Critical accessibility bug in PR #46: tile-hint with its <button
    class='hint-dismiss'> was nested INSIDE <button class='tile'>.
    Nested interactive elements are HTML5-illegal and browsers
    (specifically Android Chrome) silently dropped the inner click —
    so the × button was unclickable and hints couldn't be dismissed.

    Fix: each tile + hint is wrapped in a `<div class='tile-wrap'>`;
    the tile-hint is a SIBLING of <button class='tile'>, not a child.
    """
    r = client.get("/")
    assert r.status_code == 200
    import re

    for tile_type in ("breast", "formula", "wee", "poo"):
        assert f'data-type="{tile_type}"' in r.text
        m = re.search(
            rf'<button[^>]+data-type="{tile_type}"[^>]*>(.*?)</button>',
            r.text,
            flags=re.DOTALL,
        )
        assert m, f"{tile_type} tile button not found"
        inner = m.group(1)
        assert 'data-hint="long-press"' not in inner, (
            f"{tile_type} tile must NOT have a nested data-hint long-press "
            f"element — clicks on the inner hint-dismiss × get swallowed by "
            f"the outer <button class='tile'>. Render the hint as a sibling."
        )
    # All four long-press hints still render (just outside their tiles now).
    assert r.text.count('data-hint="long-press"') == 4


def test_today_card_count_cells_have_stable_selectors(client):
    """today-card has `<b data-count="feed">…</b>` etc. on each count."""
    r = client.get("/")
    assert r.status_code == 200
    assert '<b data-count="feed">' in r.text
    assert '<b data-count="wee">' in r.text
    assert '<b data-count="poo">' in r.text
    # Formula cc total now lives in the today-formula-strip below the
    # 3-count grid. The cell is `<b data-count="formula_ml">` in the
    # populated branch and `<b data-count="formula_ml" hidden>0</b>` in
    # the empty branch — match either via a regex.
    import re

    assert re.search(r'<b data-count="formula_ml"[^>]*>', r.text), (
        "expected `<b data-count='formula_ml'>` somewhere in today-card "
        "(empty or populated branch of today-formula-strip)"
    )


def test_today_card_uses_3_column_counts_not_counts_4(client):
    """
    Negative pin: after the v1.1.0 layout redesign, the counts grid is
    back to 3 columns. The 4-tile `counts-4` class was dropped because
    it wrapped to a "3 on top, 1 below-left" layout on phone widths.
    """
    r = client.get("/")
    assert r.status_code == 200
    assert 'class="counts counts-4"' not in r.text, (
        "today-card must NOT use the counts-4 class — its 4-tile grid "
        "wraps badly on phones (v1.1.0 regression)"
    )
    assert 'class="counts"' in r.text


def test_reports_weight_history_hidden_when_empty(client):
    """Fresh DB → weight history section is not rendered."""
    r = client.get("/reports")
    assert r.status_code == 200
    assert "data-weight-history" not in r.text


def test_reports_weight_history_renders_with_data(client):
    """One weight row → weight history section appears with the latest."""
    client.post(
        "/api/growth",
        json={
            "measured_at": "2026-05-16",
            "weight_g": 3420,
            "idempotency_key": "idem-reports-w1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    assert "data-weight-history" in r.text
    assert "Weight history" in r.text
    assert "3,420 g" in r.text
    # Single-measurement helper text appears (chart needs ≥2 points).
    assert "few days" in r.text.lower()


def test_reports_weight_history_renders_chart_with_two_points(client):
    """Two weight rows → SVG chart + 2 dots appear."""
    for d, w, idem in [
        ("2026-05-08", 3300, "idem-reports-w2a"),
        ("2026-05-15", 3420, "idem-reports-w2b"),
    ]:
        client.post(
            "/api/growth",
            json={
                "measured_at": d,
                "weight_g": w,
                "idempotency_key": idem,
                "created_by_device": "device-test",
            },
        )
    r = client.get("/reports")
    assert r.status_code == 200
    assert 'class="weight-chart"' in r.text
    # Polyline string + 2 circle dots present.
    assert "<polyline" in r.text
    assert r.text.count('class="weight-dot"') == 2


def test_reports_weight_history_table_has_delta_for_subsequent_rows(client):
    """The latest table row shows the +/− delta from the previous one."""
    for d, w, idem in [
        ("2026-05-08", 3300, "idem-reports-d1"),
        ("2026-05-15", 3420, "idem-reports-d2"),  # +120
    ]:
        client.post(
            "/api/growth",
            json={
                "measured_at": d,
                "weight_g": w,
                "idempotency_key": idem,
                "created_by_device": "device-test",
            },
        )
    r = client.get("/reports")
    assert r.status_code == 200
    # +120 g delta + delta-up class on the latest row.
    assert "+120 g" in r.text
    assert "delta-up" in r.text


def test_reports_heatmap_carries_explainer_text(client):
    """
    The 7-day heatmap had a title but no caption explaining what the
    shading meant — user reported they didn't understand it. Add a
    short legend so it reads as a pattern-finding tool, not a mystery.
    """
    r = client.get("/reports")
    assert r.status_code == 200
    # The explainer text mentions what darker cells mean.
    assert "darker" in r.text.lower() or "more events" in r.text.lower(), (
        "heatmap section must carry a short explainer caption"
    )


def test_reports_day_strip_shows_per_day_cc_total(client):
    """
    Each day-strip on the reports page shows the day's formula CC total
    inline with the day label (e.g. 'Today · 240 cc'). Without this,
    parents have to scroll all the way down to the totals table.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for i, vol in enumerate([120, 90]):
        client.post(
            "/api/events",
            json={
                "type": "formula",
                "occurred_at": f"{today}T0{i + 1}:00:00.000Z",
                "formula_brand": "Materna",
                "formula_volume_ml": vol,
                "idempotency_key": f"idem-day-strip-cc-{i}",
                "created_by_device": "device-test",
            },
        )
    r = client.get("/reports")
    assert r.status_code == 200
    # The day-strip's day-label area must include 'cc' for the today row.
    import re

    m = re.search(
        r'<div class="day-label">[^<]*Today[^<]*<span class="day-cc"[^>]*>([^<]+)</span>',
        r.text,
        flags=re.DOTALL,
    )
    assert m, "expected `<span class='day-cc'>...</span>` on today's day-label"
    assert "210" in m.group(1) and "cc" in m.group(1)


def test_reports_day_strip_omits_cc_when_no_formula(client):
    """A day with no formula logged shows the day label without the cc span."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": f"{today}T03:00:00.000Z",
            "feed_side": "L",
            "feed_duration_min": 15,
            "idempotency_key": "idem-no-cc-day",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    # No `day-cc` span on a day with no formula.
    import re

    # Search for the today strip's day-label.
    m = re.search(
        r'<div class="day-label">[^<]*Today[^<]*(<span class="day-cc"[^>]*>)?',
        r.text,
        flags=re.DOTALL,
    )
    assert m, "today's day-label not found"
    # The day-cc span shouldn't be present (group 1 is None).
    assert m.group(1) is None, (
        f"day-cc span must NOT render on days with no formula logged; got: {m.group(0)!r}"
    )


def test_reports_timeline_marks_have_title_tooltips(client):
    """
    Each timeline mark must carry a <title> element for hover/long-press
    tooltip. For formula events the title includes the cc value; for
    breast it includes side + duration.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T03:00:00.000Z",
            "formula_brand": "Materna",
            "formula_volume_ml": 240,
            "idempotency_key": "idem-tooltip-f",
            "created_by_device": "device-test",
        },
    )
    client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": f"{today}T05:00:00.000Z",
            "feed_side": "R",
            "feed_duration_min": 12,
            "idempotency_key": "idem-tooltip-b",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    # Formula tooltip must include cc value and brand.
    assert "<title>" in r.text
    assert "240 cc" in r.text
    assert "Materna" in r.text
    # Breast tooltip must include side + duration.
    assert "12m" in r.text


def test_reports_timeline_breast_event_renders_feed_class(client):
    """
    The timeline mark for a breast event must use the `.mark-feed` CSS
    class — that's the one with `fill: var(--feed)`. Previously the
    `_timeline_marks` helper emitted `m.type = "breast"`, generating
    `class='mark mark-breast'` with no matching CSS rule → mark rendered
    BLACK (SVG default fill).

    Same applies to formula. Both are conceptually "feeds" in the
    reports view.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": f"{today}T03:00:00.000Z",
            "feed_side": "L",
            "feed_duration_min": 15,
            "idempotency_key": "idem-timeline-feed-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    # The mark class must be `mark-feed`, NOT `mark-breast`.
    assert "mark-feed" in r.text, (
        "breast events must render `class='mark mark-feed'` in the timeline "
        "(maps to fill: var(--feed)). Without this they render BLACK."
    )
    assert "mark-breast" not in r.text, (
        "timeline should not emit `mark-breast` — that class has no CSS "
        "rule and renders BLACK. Map breast → feed in _timeline_marks."
    )


def test_reports_timeline_formula_event_renders_feed_class(client):
    """Symmetric: formula events also map to mark-feed."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T03:00:00.000Z",
            "formula_brand": "Materna",
            "formula_volume_ml": 120,
            "idempotency_key": "idem-timeline-feed-2",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    assert "mark-feed" in r.text
    assert "mark-formula" not in r.text


def test_reports_timeline_marks_use_wider_width(client):
    """
    The reports timeline marks were `<rect width="4">` — at Pixel 9's
    high DPI that renders ~1.6 CSS px and the user couldn't see feed
    marks at all. Widen to 6 (~2.4 CSS px) so events are visible at
    arm's length without changing the timeline density.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": f"{today}T03:00:00.000Z",
            "feed_side": "L",
            "feed_duration_min": 15,
            "idempotency_key": "idem-timeline-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    # No `width="4"` marks (the old too-thin value).
    import re

    assert not re.search(r'<rect[^>]*\bwidth="4"', r.text), (
        "reports timeline marks must NOT use width='4' (too thin to see "
        "on high-DPI phones); use width='6' instead"
    )
    # At least one `width="6"` mark for the logged event.
    assert re.search(r'<rect[^>]*\bwidth="6"', r.text), (
        "reports timeline must use width='6' marks for visibility"
    )


def test_today_card_has_formula_strip(client):
    """
    Today-card has a dedicated `today-formula-strip` element below the
    3-count grid carrying the daily cc total. Pin its presence and
    its stable `data-formula-strip` selector for JS targeting.
    """
    r = client.get("/")
    assert r.status_code == 200
    assert "data-formula-strip" in r.text
    assert "today-formula-strip" in r.text


def test_today_card_formula_strip_populated_when_formula_logged(client):
    """The strip shows the cc total when at least one formula is logged today."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T03:00:00.000Z",
            "formula_brand": "Materna",
            "formula_volume_ml": 120,
            "idempotency_key": "idem-strip-pop-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    import re

    # Extract the strip block and assert it contains both the number and
    # the unit / context language.
    m = re.search(
        r'<div class="today-formula-strip"[^>]*>(.*?)</div>',
        r.text,
        flags=re.DOTALL,
    )
    assert m, "today-formula-strip not found"
    block = m.group(1)
    assert "120" in block, f"cc total 120 not in strip: {block!r}"
    assert "cc formula" in block or "cc" in block


def test_today_card_formula_strip_empty_branch_preserves_selector(client):
    """
    Empty-state branch (no formula today) must STILL include the
    `<b data-count="formula_ml">` cell so `bumpOverviews` can find it
    when an optimistic POST lands. The cell is `hidden` in this branch
    so it doesn't visually show "0 cc formula".
    """
    r = client.get("/")
    assert r.status_code == 200
    import re

    # Strip is present even on empty state.
    m = re.search(
        r'<div class="today-formula-strip"[^>]*>(.*?)</div>',
        r.text,
        flags=re.DOTALL,
    )
    assert m, "today-formula-strip must render even with no formula logged"
    block = m.group(1)
    # The data-count cell must exist (hidden) so JS can find + un-hide it.
    assert 'data-count="formula_ml"' in block, (
        "even in empty state, the data-count='formula_ml' cell must be "
        "present (hidden) so bumpOverviews can update it on an optimistic POST"
    )
    # And the empty-state copy must be readable.
    assert "no formula" in block.lower()


def test_today_card_renders_formula_cc_total(client):
    """
    Logging two formula feeds today should sum into the formula_ml tile.
    Pin that the integer total renders correctly.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for i, vol in enumerate([120, 90]):
        client.post(
            "/api/events",
            json={
                "type": "formula",
                "occurred_at": f"{today}T0{i + 1}:00:00.000Z",
                "formula_brand": "Materna",
                "formula_volume_ml": vol,
                "idempotency_key": f"idem-cc-today-{i}",
                "created_by_device": "device-test",
            },
        )
    r = client.get("/")
    assert r.status_code == 200
    import re

    m = re.search(r'<b data-count="formula_ml">(\d+)</b>', r.text)
    assert m, "formula_ml big-number tile not found"
    assert int(m.group(1)) == 210


def test_last_days_table_has_formula_cc_column(client):
    """
    The Last-3-days mini-table on `/` carries a `data-col="formula_ml"`
    cell per day so JS can target it and parents can scan cc per day.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T03:00:00.000Z",
            "formula_brand": "Materna",
            "formula_volume_ml": 150,
            "idempotency_key": "idem-cc-lastdays-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert 'data-col="formula_ml"' in r.text
    # The 150cc value should render in today's row.
    import re

    m = re.search(
        rf'<tr data-day="{today}">(.*?)</tr>',
        r.text,
        flags=re.DOTALL,
    )
    assert m, "today's row not found in last-days table"
    assert "150" in m.group(1)


def test_reports_totals_table_has_formula_cc_column(client):
    """
    The reports daily-totals table adds a 🍼 cc column alongside the
    existing 🍼 count column — 14-day intake trend visible per day.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T03:00:00.000Z",
            "formula_brand": "Materna",
            "formula_volume_ml": 180,
            "idempotency_key": "idem-cc-rpts-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    # Header marker for the new column.
    assert 'data-col-totals="formula_ml"' in r.text
    # The 180cc value renders in the totals row for today.
    assert "180" in r.text


def test_today_card_last_of_each_rows_have_stable_selectors(client):
    """The 'last of each' list rows have `data-last="feed"` etc."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'data-last="feed"' in r.text
    assert 'data-last="wee"' in r.text
    assert 'data-last="poo"' in r.text


def test_last_days_rows_have_stable_selectors(client):
    """Each row in the mini-table has `data-day="YYYY-MM-DD"` + `data-col` cells."""
    r = client.get("/")
    assert r.status_code == 200
    # At least one day-row + the three data columns
    import re

    assert re.search(r'<tr data-day="\d{4}-\d{2}-\d{2}"', r.text), (
        "last-days rows should expose `data-day` attribute for JS targeting"
    )
    assert 'data-col="feed"' in r.text
    assert 'data-col="wee"' in r.text
    assert 'data-col="poo"' in r.text


def test_index_renders_breast_and_formula_tiles(client):
    """4 tiles total post-#5: BREAST, FORMULA, WEE, POO."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'data-type="breast"' in r.text
    assert 'data-type="formula"' in r.text
    assert "BREAST" in r.text
    assert "FORMULA" in r.text


def test_event_row_has_row_menu_button(client):
    """
    Every event row carries a trailing-edge `⋯` button (`data-row-menu`)
    that opens an Edit/Delete sheet. Discoverable alternative to swipe.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "wee",
            "occurred_at": f"{today}T03:00:00.000Z",
            "idempotency_key": "idem-row-menu-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "data-row-menu" in r.text
    assert 'aria-label="Row actions"' in r.text
    # And the trailing-edge glyph.
    assert "⋯" in r.text


def test_event_row_has_aria_label(client):
    """
    Each row gets an aria-label describing both gestures, so SR users
    know the row is interactive AND know about swipe.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "wee",
            "occurred_at": f"{today}T03:00:00.000Z",
            "idempotency_key": "idem-row-aria-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert 'aria-label="Tap to edit; swipe left to delete"' in r.text


def test_first_row_hint_rendered_when_events_present(client):
    """
    With at least one event logged, a dismissible 'Tap to edit · swipe
    left to delete' hint renders ABOVE the event list (outside the
    `<ul>` to avoid the sticky day-header's z-index context).
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "wee",
            "occurred_at": f"{today}T03:00:00.000Z",
            "idempotency_key": "idem-frh-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert 'data-hint="first-row"' in r.text
    assert "Tap to edit" in r.text and "swipe left to delete" in r.text


def test_first_row_hint_absent_on_empty_state(client):
    """No events → no first-row hint (the empty-state copy carries the cue)."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'data-hint="first-row"' not in r.text


def test_first_row_hint_emitted_only_once(client):
    """
    Multiple events across multiple days → still only ONE first-row
    hint (the hint is for the list as a whole, not per row).
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for i in range(3):
        client.post(
            "/api/events",
            json={
                "type": "wee",
                "occurred_at": f"{today}T0{i + 1}:00:00.000Z",
                "idempotency_key": f"idem-frh-multi-{i}",
                "created_by_device": "device-test",
            },
        )
    r = client.get("/")
    assert r.status_code == 200
    assert r.text.count('data-hint="first-row"') == 1


def test_first_row_hint_starts_hidden(client):
    """Hint starts `hidden`; JS un-hides if not dismissed."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "wee",
            "occurred_at": f"{today}T03:00:00.000Z",
            "idempotency_key": "idem-frh-hidden",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    import re

    m = re.search(r'<[^>]*data-hint="first-row"([^>]*)>', r.text)
    assert m
    assert "hidden" in m.group(1)


def test_tile_long_press_caption_rendered_for_each_tile(client):
    """
    Every tile (4 total: breast / formula / wee / poo) carries a small
    caption hint announcing the long-press skip-modal quick-log.
    Without this, the 3-second hold gesture is undiscoverable.
    """
    r = client.get("/")
    assert r.status_code == 200
    assert r.text.count('data-hint="long-press"') == 4, (
        "expected exactly 4 long-press hint nodes (one per tile)"
    )
    assert r.text.count("Hold 3s to log instantly") == 4


def test_tile_caption_starts_hidden(client):
    """
    The caption renders with the `hidden` attribute by default; app.js
    un-hides it on DOMContentLoaded only when the dismissal flag isn't
    set. Pinned because a regression here would show the hint to every
    parent forever.
    """
    r = client.get("/")
    assert r.status_code == 200
    import re

    # Every long-press hint node should have the `hidden` attribute.
    nodes = re.findall(
        r'<div class="tile-hint" data-hint="long-press"([^>]*)>',
        r.text,
    )
    assert len(nodes) == 4
    for attrs in nodes:
        assert "hidden" in attrs, (
            f"long-press hint must carry the hidden attribute; got attrs={attrs!r}"
        )


def test_sync_badge_has_explainer_button(client):
    """
    The header sync dot must be a real <button> with an aria-label,
    and carry `data-sync-explain` so the JS click handler can attach.
    Previously a <span> with a static title="Connection" — invisible
    to keyboard users and unhelpful for two-parent onboarding.
    """
    r = client.get("/")
    assert r.status_code == 200
    assert "data-sync-explain" in r.text, (
        "expected the sync badge to expose `data-sync-explain` for JS wiring"
    )
    assert 'aria-label="Connection status"' in r.text, (
        "sync badge button must declare aria-label='Connection status'"
    )


def test_event_row_does_not_render_long_notes_inline(client):
    """
    Inline notes text in `.ev-detail` overlapped the relative-time
    column on long notes (v1.1.0 production feedback). The 📝 icon
    is the at-a-glance signal that notes exist; the full notes are
    visible in the edit modal on tap. Pin that the inline notes
    text is NOT rendered in the row at all.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    long_note = "this-is-a-deliberately-long-unique-comment-marker-XYZ123"
    client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": f"{today}T03:00:00.000Z",
            "feed_side": "L",
            "feed_duration_min": 15,
            "notes": long_note,
            "idempotency_key": "idem-no-inline-notes-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    # The 📝 icon is present.
    assert "📝" in r.text
    # But the literal note text is NOT rendered anywhere in the page —
    # the icon is the existence indicator; full notes only show in modal.
    assert long_note not in r.text, (
        "event row must NOT include the inline notes text — long notes "
        "overlapped the relative-time column. Show only the 📝 icon; "
        "full notes appear in the edit modal on tap."
    )


def test_event_row_shows_notes_icon_when_notes_present(client):
    """
    Event rows with non-empty notes show a small 📝 indicator inside
    `.ev-detail`. Without this, users can't tell at a glance which rows
    carry hidden notes (the full notes text is also rendered, but it
    truncates at 50% width, so a deliberate icon is the at-a-glance
    affordance).
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "wee",
            "occurred_at": f"{today}T03:00:00.000Z",
            "notes": "loose",
            "idempotency_key": "idem-notes-icon-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert 'class="ev-notes-icon"' in r.text
    assert "📝" in r.text


def test_event_row_omits_notes_icon_when_no_notes(client):
    """Symmetric: rows without notes must NOT carry the icon."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "wee",
            "occurred_at": f"{today}T03:00:00.000Z",
            "idempotency_key": "idem-notes-icon-2",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "ev-notes-icon" not in r.text


def test_index_empty_state_copy_actionable(client):
    """
    Fresh-install empty state must direct the user up to the tiles
    rather than just commenting on quiet ("Quiet night 💤" gave no
    next-action cue).
    """
    r = client.get("/")
    assert r.status_code == 200
    assert "Tap a tile above to log your first entry" in r.text
    assert "Quiet night" not in r.text


def test_tile_no_recent_uses_dedicated_class(client):
    """
    Tiles with no recent event must use a dedicated `.no-recent` class
    rather than the generic `.muted` so the placeholder is visually
    distinct from real muted metadata (formula brand, feed side, etc.).
    """
    r = client.get("/")
    assert r.status_code == 200
    # Fresh DB — every tile-ago region should show the dedicated class.
    assert r.text.count('class="no-recent"') >= 4, (
        "expected `.no-recent` on every tile's empty-state placeholder "
        "(breast/formula/wee/poo when no event of that type exists)"
    )


def test_tile_no_recent_absent_when_recent_event_exists(client):
    """
    The `.no-recent` placeholder must disappear from a tile once an
    event of that type is logged. Belt-and-braces — symmetric to the
    presence test above.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "wee",
            "occurred_at": f"{today}T03:00:00.000Z",
            "idempotency_key": "idem-norec-w-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    import re

    m = re.search(
        r'<div class="tile-ago" id="ago-wee">(.*?)</div>',
        r.text,
        flags=re.DOTALL,
    )
    assert m, "wee tile-ago region not found"
    assert "no-recent" not in m.group(1), (
        "wee tile must drop the .no-recent placeholder once a wee is logged"
    )
    # Other tiles still show it (no breast/formula/poo logged).
    for tile_id in ("ago-breast", "ago-formula", "ago-poo"):
        m = re.search(
            rf'<div class="tile-ago" id="{tile_id}">(.*?)</div>',
            r.text,
            flags=re.DOTALL,
        )
        assert m and "no-recent" in m.group(1), (
            f"{tile_id} should still carry .no-recent (no event of that type)"
        )


def test_formula_tile_shows_recent_when_breast_is_more_recent(client):
    """
    Production bug (May 2026): with a formula logged earlier and a breast
    logged after it, the formula tile rendered "no recent" because the
    tile read from the combined `feed` key which always pointed at the
    most-recent feed of EITHER kind. Each tile must drive off its own
    per-type "last X".
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T01:00:00.000Z",
            "formula_brand": "Materna",
            "formula_volume_ml": 120,
            "idempotency_key": "idem-tile-f-1",
            "created_by_device": "device-test",
        },
    )
    client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": f"{today}T05:00:00.000Z",
            "feed_side": "L",
            "feed_duration_min": 12,
            "idempotency_key": "idem-tile-b-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    # The formula tile's tile-ago region must NOT show "no recent" — a
    # formula WAS logged today. Anchor on the formula tile's id.
    import re

    m = re.search(
        r'<div class="tile-ago" id="ago-formula">(.*?)</div>',
        r.text,
        flags=re.DOTALL,
    )
    assert m, "formula tile-ago region not found"
    formula_ago = m.group(1)
    assert "no recent" not in formula_ago, (
        "formula tile must show the last formula time even when the most-"
        "recent feed overall is a breast feed"
    )
    assert "Materna" in formula_ago

    # Symmetric: the breast tile must also still show its own recent.
    m = re.search(
        r'<div class="tile-ago" id="ago-breast">(.*?)</div>',
        r.text,
        flags=re.DOTALL,
    )
    assert m, "breast tile-ago region not found"
    assert "no recent" not in m.group(1)


def test_breast_tile_shows_recent_when_formula_is_more_recent(client):
    """Mirror of the above: breast logged earlier, formula more recently."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": f"{today}T01:00:00.000Z",
            "feed_side": "R",
            "feed_duration_min": 9,
            "idempotency_key": "idem-tile-b-2",
            "created_by_device": "device-test",
        },
    )
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T05:00:00.000Z",
            "formula_brand": "Nutrilon",
            "formula_volume_ml": 90,
            "idempotency_key": "idem-tile-f-2",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    import re

    m = re.search(
        r'<div class="tile-ago" id="ago-breast">(.*?)</div>',
        r.text,
        flags=re.DOTALL,
    )
    assert m
    assert "no recent" not in m.group(1)


def test_index_renders_formula_event_row_with_brand_and_volume(client):
    """A logged formula entry shows up with brand + volume in the row."""
    # Today's date so the event lands inside the home page's last-3-days
    # filter window (same drift class as test_index_shows_event_in_grouped_list).
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T03:00:00.000Z",
            "formula_brand": "Materna",
            "formula_volume_ml": 120,
            "idempotency_key": "idem-pg-formula-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "🍼" in r.text
    assert "Materna" in r.text
    assert "120 cc" in r.text


def test_reports_renders_breast_and_formula_columns(client):
    """Totals table breaks out breast vs formula as separate columns."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    # 2 breast + 1 formula today
    client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": f"{today}T03:00:00.000Z",
            "feed_side": "L",
            "feed_duration_min": 15,
            "idempotency_key": "idem-rpts-bf-1",
            "created_by_device": "device-test",
        },
    )
    client.post(
        "/api/events",
        json={
            "type": "breast",
            "occurred_at": f"{today}T05:00:00.000Z",
            "feed_side": "R",
            "feed_duration_min": 12,
            "idempotency_key": "idem-rpts-bf-2",
            "created_by_device": "device-test",
        },
    )
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": f"{today}T07:00:00.000Z",
            "formula_brand": "Materna",
            "formula_volume_ml": 120,
            "idempotency_key": "idem-rpts-bf-3",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    # Header has the emoji column titles for breast / formula
    thead_start = r.text.find("<thead>")
    thead_end = r.text.find("</thead>", thead_start)
    thead = r.text[thead_start:thead_end]
    assert "🤱" in thead
    assert "🍼" in thead
    # tbody has 2 breast + 1 formula for today
    tbody_start = r.text.find('id="totals-body"')
    tbody_end = r.text.find("</tbody>", tbody_start)
    tbody = r.text[tbody_start:tbody_end]
    assert "<td>2</td>" in tbody
    assert "<td>1</td>" in tbody


def test_reports_totals_table_contains_data_rows(client):
    """The totals table body has at least one <tr> when events exist."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for i in range(2):
        client.post(
            "/api/events",
            json=_payload(
                idempotency_key=f"idem-rpts-tot-{i:04d}",
                occurred_at=f"{today}T{i:02d}:00:00.000Z",
                feed_duration_min=15 + i,
            ),
        )
    r = client.get("/reports")
    assert r.status_code == 200
    tbody_start = r.text.find('id="totals-body"')
    assert tbody_start != -1
    tbody_end = r.text.find("</tbody>", tbody_start)
    tbody = r.text[tbody_start:tbody_end]
    assert "<tr>" in tbody  # at least one data row
    # Avg-feed cell is "%.0f min" — for 15 and 16 min, avg = 15.5 → "16 min"
    assert "16 min" in tbody


def test_reports_timeline_legend_includes_vitd(client):
    """The Last 7 days timeline-legend must have a vit D entry alongside feed/wee/poo."""
    r = client.get("/reports")
    assert r.status_code == 200
    legend_start = r.text.find('class="timeline-legend"')
    assert legend_start != -1, "timeline-legend container not found"
    legend_end = r.text.find("</div>", legend_start)
    legend = r.text[legend_start:legend_end]
    assert "lg-vitd" in legend, "legend must include the `lg-vitd` dot for #8.5"
    assert "vit D" in legend, "legend must label the vit D entry"


def test_reports_totals_includes_vitd_column(client):
    """
    The daily totals table gains a 💊 column showing ✓ for days with at
    least one vit D event, `—` otherwise.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "vitd",
            "occurred_at": f"{today}T09:00:00.000Z",
            "idempotency_key": "idem-rpts-vitd-1",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    # Stable selector for the column.
    assert 'data-col-totals="vitd"' in r.text, (
        "reports totals table must have a column with `data-col-totals='vitd'`"
    )
    # The day with a vit D event shows ✓ in the totals row.
    tbody_start = r.text.find('id="totals-body"')
    tbody_end = r.text.find("</tbody>", tbody_start)
    tbody = r.text[tbody_start:tbody_end]
    assert "✓" in tbody, "today's totals row must show ✓ in the 💊 column"


def test_reports_timeline_renders_vitd_mark(client):
    """A vit D event renders with `class='mark mark-vitd'` in the timeline SVG."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "vitd",
            "occurred_at": f"{today}T09:00:00.000Z",
            "idempotency_key": "idem-rpts-vitd-mark",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    assert "mark-vitd" in r.text, (
        "vit D events must render `class='mark mark-vitd'` so the gold fill rule applies"
    )


def test_reports_timeline_vitd_tooltip_says_vit_d(client):
    """The vit D mark's <title> tooltip carries the human label 'Vit D'."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    client.post(
        "/api/events",
        json={
            "type": "vitd",
            "occurred_at": f"{today}T09:00:00.000Z",
            "idempotency_key": "idem-rpts-vitd-tip",
            "created_by_device": "device-test",
        },
    )
    r = client.get("/reports")
    assert r.status_code == 200
    # The tooltip is `<title>HH:MM · Vit D</title>` for vit D events.
    assert "Vit D" in r.text, "vit D timeline mark tooltip must carry the 'Vit D' label"
