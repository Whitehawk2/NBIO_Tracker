import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from .. import repo
from ..config import settings
from ..db import get_conn
from ..sse import broker, format_sse, stream

router = APIRouter(prefix="/api")

SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable nginx buffering, harmless elsewhere
}


@router.get("/stream")
async def sse_stream(
    request: Request,
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    queue = broker.subscribe()

    replay_chunks: list[str] = []
    if last_event_id:
        try:
            last_id = int(last_event_id)
        except ValueError:
            last_id = 0
        rows = repo.list_events_since_id(conn, last_id, settings.sse_replay_cap)
        for r in rows:
            replay_chunks.append(format_sse("event.created", r["id"], r))

    async def generator():
        for chunk in replay_chunks:
            yield chunk
        try:
            async for chunk in stream(queue):
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(generator(), headers=SSE_HEADERS, media_type="text/event-stream")
