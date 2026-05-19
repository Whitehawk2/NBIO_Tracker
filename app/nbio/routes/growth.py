"""Growth measurements (v1.1.1 — weight tracking; #55 forward-compat)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from .. import repo
from ..db import get_conn
from ..models import GrowthCreate, GrowthPatch
from ..sse import broker

router = APIRouter(prefix="/api")


@router.get("/growth")
def list_growth(conn: sqlite3.Connection = Depends(get_conn)):
    return {"growth": repo.growth_list(conn)}


@router.get("/growth/{growth_id}")
def get_growth(growth_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    row = repo.fetch_growth(conn, growth_id)
    if row is None:
        raise HTTPException(404, "Not found")
    return {"growth": row}


@router.post("/growth")
async def create_growth(
    payload: GrowthCreate,
    conn: sqlite3.Connection = Depends(get_conn),
):
    status, row = repo.growth_create(conn, payload)
    body: dict = {"status": status, "growth": row}
    if status != "already_exists":
        await broker.publish("growth.created", row["id"], row)
    return body


@router.patch("/growth/{growth_id}")
async def patch_growth(
    growth_id: int,
    patch: GrowthPatch,
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = repo.growth_patch(conn, growth_id, patch)
    if row is None:
        raise HTTPException(404, "Not found")
    await broker.publish("growth.updated", growth_id, row)
    return {"status": "updated", "growth": row}


@router.delete("/growth/{growth_id}")
async def delete_growth(
    growth_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = repo.growth_soft_delete(conn, growth_id)
    if row is None:
        raise HTTPException(404, "Not found")
    await broker.publish("growth.deleted", growth_id, {"id": growth_id})
    return {"status": "deleted", "id": growth_id}


@router.post("/growth/{growth_id}/undelete")
async def undelete_growth(
    growth_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = repo.growth_undelete(conn, growth_id)
    if row is None:
        raise HTTPException(404, "Not found")
    await broker.publish("growth.undeleted", growth_id, row)
    return {"status": "undeleted", "growth": row}
