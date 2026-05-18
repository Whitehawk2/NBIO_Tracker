"""
Runtime-editable settings + baby info + server-info + data export (#6).

All settings routes take `Depends(current_actor)` as future-auth seam —
today the actor is unused inside the body (the resolver merely populates
it from the X-Device-Id header), but the signature stays stable when
session / JWT auth lands.

Each PATCH publishes an SSE event so two-parent setups stay in sync:
- `settings.updated` for /api/settings
- `baby.updated`     for /api/babies
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
import tomllib
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from .. import repo
from ..auth import current_actor
from ..config import settings
from ..db import get_conn
from ..models import Actor, AppSettingsUpdate, BabyUpdate
from ..sse import broker
from ..version import static_assets_hash

router = APIRouter(prefix="/api")

# Captured at module import. Pyproject is read once; uptime is the
# delta from this monotonic baseline (immune to wall-clock jumps).
START_MONO = time.monotonic()
_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _app_version() -> str:
    with _PYPROJECT.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


APP_VERSION = _app_version()

# Column order for the CSV / JSON exports. Locked here so a schema
# addition doesn't silently reorder downstream consumers (Excel
# templates etc.). When events table gets new columns, add them
# to this tuple deliberately.
EXPORT_COLUMNS = (
    "id",
    "baby_id",
    "type",
    "occurred_at",
    "feed_side",
    "feed_duration_min",
    "poo_quality",
    "notes",
    "formula_brand",
    "formula_volume_ml",
    "idempotency_key",
    "created_by_device",
    "created_at",
    "updated_at",
    "deleted_at",
)


def _all_events_for_export(conn: sqlite3.Connection) -> list[dict]:
    cols = ", ".join(EXPORT_COLUMNS)
    cur = conn.execute(f"SELECT {cols} FROM events ORDER BY id ASC")
    return [dict(r) for r in cur.fetchall()]


@router.get("/settings")
def get_settings(
    conn: sqlite3.Connection = Depends(get_conn),
    actor: Actor = Depends(current_actor),
) -> dict:
    return {"settings": repo.app_settings_read(conn)}


@router.patch("/settings")
async def patch_settings(
    payload: AppSettingsUpdate,
    conn: sqlite3.Connection = Depends(get_conn),
    actor: Actor = Depends(current_actor),
) -> dict:
    row = repo.app_settings_update(conn, payload)
    await broker.publish("settings.updated", 0, row)
    return {"status": "ok", "settings": row}


@router.patch("/babies")
async def patch_baby(
    payload: BabyUpdate,
    conn: sqlite3.Connection = Depends(get_conn),
    actor: Actor = Depends(current_actor),
) -> dict:
    row = repo.update_baby(conn, payload)
    await broker.publish("baby.updated", 0, row)
    return {"status": "ok", "baby": row}


@router.get("/server-info")
def server_info(
    actor: Actor = Depends(current_actor),
) -> dict:
    """Read-only runtime info — version, static-hash, DB size, uptime."""
    try:
        db_size = Path(settings.db_path).stat().st_size
    except (OSError, ValueError):
        # `:memory:` or missing file → 0. Test paths use in-memory DBs.
        db_size = 0
    return {
        "version": APP_VERSION,
        "static_hash": static_assets_hash(),
        "db_size_bytes": db_size,
        "uptime_seconds": int(time.monotonic() - START_MONO),
    }


@router.get("/export/events.json")
def export_events_json(
    conn: sqlite3.Connection = Depends(get_conn),
    actor: Actor = Depends(current_actor),
) -> Response:
    """All events as a minified JSON array. Includes soft-deleted rows."""
    rows = _all_events_for_export(conn)
    body = json.dumps(rows, separators=(",", ":"))
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="events.json"'},
    )


@router.get("/export/events.csv")
def export_events_csv(
    conn: sqlite3.Connection = Depends(get_conn),
    actor: Actor = Depends(current_actor),
) -> Response:
    """
    All events as RFC 4180 CSV with a UTF-8 BOM (Excel-friendly) and
    a header row. NULLs render as empty cells. Includes soft-deleted.
    """
    rows = _all_events_for_export(conn)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for r in rows:
        writer.writerow(["" if r[c] is None else r[c] for c in EXPORT_COLUMNS])
    body = "﻿" + buf.getvalue()  # UTF-8 BOM
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="events.csv"'},
    )
