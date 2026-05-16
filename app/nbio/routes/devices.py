import sqlite3

from fastapi import APIRouter, Depends

from .. import repo
from ..db import get_conn
from ..models import DeviceUpsert
from ..sse import broker

router = APIRouter(prefix="/api")


@router.get("/devices")
def list_devices(conn: sqlite3.Connection = Depends(get_conn)):
    return {"devices": repo.list_devices(conn)}


@router.put("/devices/{device_id}")
async def upsert_device(
    device_id: str,
    payload: DeviceUpsert,
    conn: sqlite3.Connection = Depends(get_conn),
):
    device = repo.upsert_device(conn, device_id, payload)
    await broker.publish("device.updated", 0, device)
    return {"status": "ok", "device": device}
