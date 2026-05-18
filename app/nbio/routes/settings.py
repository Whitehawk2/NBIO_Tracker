"""
Runtime-editable settings + baby info (#6).

All routes take `Depends(current_actor)` as future-auth seam — today
the actor is unused inside the body (the resolver merely populates it
from the X-Device-Id header), but the signature stays stable when
session / JWT auth lands.

Each PATCH publishes an SSE event so two-parent setups stay in sync:
- `settings.updated` for /api/settings
- `baby.updated`     for /api/babies
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .. import repo
from ..auth import current_actor
from ..db import get_conn
from ..models import Actor, AppSettingsUpdate, BabyUpdate
from ..sse import broker

router = APIRouter(prefix="/api")


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
