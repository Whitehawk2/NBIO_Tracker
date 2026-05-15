import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repo
from ..db import get_conn
from ..models import EventCreate, EventPatch
from ..sse import broker

router = APIRouter(prefix="/api")


@router.get("/events")
def list_events(
    since: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return {"events": repo.list_events(conn, since=since, limit=limit)}


@router.post("/events")
async def create_event(
    payload: EventCreate,
    conn: sqlite3.Connection = Depends(get_conn),
):
    status, event, dup = repo.create_event(conn, payload)
    body: dict = {"status": status, "event": event}
    if dup:
        body["duplicate_of"] = dup
    if status != "already_exists":
        await broker.publish("event.created", event["id"], event)
    return body


@router.patch("/events/{event_id}")
async def patch_event(
    event_id: int,
    patch: EventPatch,
    conn: sqlite3.Connection = Depends(get_conn),
):
    event = repo.patch_event(conn, event_id, patch)
    if event is None:
        raise HTTPException(404, "Not found")
    await broker.publish("event.updated", event_id, event)
    return {"status": "updated", "event": event}


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    event = repo.soft_delete_event(conn, event_id)
    if event is None:
        raise HTTPException(404, "Not found")
    await broker.publish("event.deleted", event_id, {"id": event_id})
    return {"status": "deleted", "id": event_id}


@router.post("/events/{event_id}/undelete")
async def undelete_event(
    event_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    event = repo.undelete_event(conn, event_id)
    if event is None:
        raise HTTPException(404, "Not found")
    await broker.publish("event.undeleted", event_id, event)
    return {"status": "undeleted", "event": event}


@router.get("/feeds/last-side")
def get_last_feed_side(conn: sqlite3.Connection = Depends(get_conn)):
    return {"last_side": repo.last_feed_side(conn)}
