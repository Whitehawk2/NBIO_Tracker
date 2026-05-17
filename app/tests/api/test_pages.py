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


def test_index_shows_event_in_grouped_list(client):
    """An event posted via the API appears in the grouped event list."""
    client.post("/api/events", json=_payload(idempotency_key="idem-index-1"))
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


def test_index_empty_state_message(client):
    """No events → the warm empty-state copy is visible."""
    r = client.get("/")
    assert "Quiet night" in r.text


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


def test_index_renders_breast_and_formula_tiles(client):
    """4 tiles total post-#5: BREAST, FORMULA, WEE, POO."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'data-type="breast"' in r.text
    assert 'data-type="formula"' in r.text
    assert "BREAST" in r.text
    assert "FORMULA" in r.text


def test_index_renders_formula_event_row_with_brand_and_volume(client):
    """A logged formula entry shows up with brand + volume in the row."""
    client.post(
        "/api/events",
        json={
            "type": "formula",
            "occurred_at": "2026-05-16T03:00:00.000Z",
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
