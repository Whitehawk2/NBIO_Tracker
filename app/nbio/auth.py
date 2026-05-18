"""
Future-auth seam (#6).

Today this resolves an Actor from the `X-Device-Id` header.

- Known device id (header → `devices` table hit) → device-kind Actor
  carrying that device's name + color.
- Header missing OR device unknown → anonymous Actor (kind='anonymous',
  id='anon'). We don't 401 today — the existing app has no auth and
  all routes are read-tolerant; turning this resolver into a gate is
  the future auth ticket's job.

When session / JWT auth lands, replace the body of `current_actor`
(parse cookie / Bearer header, look up user). Route signatures
(`Depends(current_actor)`) don't change. Add `"user"` to ActorKind in
`models.py` and the existing Actor consumers Just Work.
"""

from __future__ import annotations

import sqlite3

from fastapi import Depends, Request

from .db import get_conn
from .models import Actor

ANONYMOUS = Actor(id="anon", kind="anonymous", name=None, color=None)


async def current_actor(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> Actor:
    """Resolve the requestor to an Actor. See module docstring."""
    device_id = request.headers.get("x-device-id")
    if not device_id:
        return ANONYMOUS
    row = conn.execute(
        "SELECT id, name, color FROM devices WHERE id = ?",
        (device_id,),
    ).fetchone()
    if row is None:
        return ANONYMOUS
    return Actor(id=row["id"], kind="device", name=row["name"], color=row["color"])
