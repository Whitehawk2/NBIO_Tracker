"""
/api/events/export.{json,csv} — data export (#6 settings → Data tab).

JSON is the canonical machine-readable backup; CSV is human-friendly
(opens in Excel/Numbers with the UTF-8 BOM for non-ASCII names).
Both include soft-deleted rows so the export is a true backup.
"""

from __future__ import annotations

import csv
import io
import json


def _payload(**over):
    base = {
        "type": "breast",
        "occurred_at": "2026-05-16T03:00:00.000Z",
        "feed_side": "L",
        "feed_duration_min": 15,
        "idempotency_key": "idem-export-aa",
        "created_by_device": "device-test",
    }
    base.update(over)
    return base


def test_export_json_returns_array_of_events(client):
    client.post("/api/events", json=_payload(idempotency_key="idem-ex-1"))
    client.post(
        "/api/events",
        json=_payload(
            type="wee",
            occurred_at="2026-05-16T04:00:00.000Z",
            idempotency_key="idem-ex-2",
        ),
    )
    r = client.get("/api/export/events.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = json.loads(r.text)
    assert isinstance(body, list)
    assert len(body) == 2
    types = {row["type"] for row in body}
    assert types == {"breast", "wee"}


def test_export_json_includes_soft_deleted(client):
    """Backups must round-trip — include deleted rows with deleted_at populated."""
    created = client.post("/api/events", json=_payload(idempotency_key="idem-del-1")).json()
    client.delete(f"/api/events/{created['event']['id']}")
    body = json.loads(client.get("/api/export/events.json").text)
    assert len(body) == 1
    assert body[0]["deleted_at"] is not None


def test_export_json_attachment_header(client):
    r = client.get("/api/export/events.json")
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "events" in r.headers.get("content-disposition", "")


def test_export_csv_has_header_row(client):
    client.post("/api/events", json=_payload(idempotency_key="idem-csv-1"))
    r = client.get("/api/export/events.csv")
    assert r.status_code == 200
    # Content-Type must be CSV with charset.
    assert "text/csv" in r.headers["content-type"]
    text = r.text
    # UTF-8 BOM for Excel.
    assert text.startswith("﻿"), "CSV must lead with UTF-8 BOM for Excel compatibility"
    # First non-BOM row is the header.
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader)
    # Spot-check critical columns are present.
    critical = (
        "id",
        "type",
        "occurred_at",
        "feed_side",
        "formula_volume_ml",
        "notes",
        "deleted_at",
    )
    for col in critical:
        assert col in header, f"CSV header missing column: {col}"


def test_export_csv_quotes_commas_in_notes(client):
    """RFC 4180 quoting: a note with a comma stays in one field."""
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-csv-comma",
            notes="loose, watery, smelly",
        ),
    )
    r = client.get("/api/export/events.csv")
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    # Find the data row (skip header).
    data = rows[1]
    notes_idx = rows[0].index("notes")
    assert data[notes_idx] == "loose, watery, smelly"


def test_export_csv_renders_nulls_as_empty(client):
    """Nullable fields appear as empty cells, not the string 'None'."""
    client.post(
        "/api/events",
        json=_payload(
            idempotency_key="idem-csv-null",
            notes=None,
            poo_quality=None,
        ),
    )
    r = client.get("/api/export/events.csv")
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    header, data = rows[0], rows[1]
    assert data[header.index("notes")] == ""
    assert data[header.index("poo_quality")] == ""


def test_export_csv_attachment_header(client):
    r = client.get("/api/export/events.csv")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "events" in cd
    assert ".csv" in cd
