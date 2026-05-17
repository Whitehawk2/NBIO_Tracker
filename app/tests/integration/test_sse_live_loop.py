"""
Cover the live-loop body in stream.py (lines 45-47): after replay finishes,
we read from the queue, check disconnect, yield. The other SSE tests use
a disconnect mock that returns True immediately; here we let it return
False once, publish to the queue, then return True to break.
"""

import asyncio

import pytest

from nbio import sse
from nbio.routes.stream import sse_stream


class _RequestThatGoesOffline:
    """is_disconnected returns False then True (single transition)."""

    def __init__(self):
        self._calls = 0

    async def is_disconnected(self):
        self._calls += 1
        return self._calls > 1


@pytest.mark.asyncio
async def test_live_loop_yields_then_disconnect(conn):
    req = _RequestThatGoesOffline()
    resp = await sse_stream(req, last_event_id=None, conn=conn)

    # Publish an event to drive the queue.get path
    await sse.broker.publish("event.created", 1, {"id": 1, "type": "breast"})

    out = []
    gen = resp.body_iterator
    try:
        chunk = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        out.append(chunk)
    except (TimeoutError, StopAsyncIteration):
        pass

    # Now drain — disconnect should be True on next iteration → break.
    try:
        async for c in gen:
            if isinstance(c, bytes):
                c = c.decode("utf-8")
            out.append(c)
    except Exception:
        pass

    text = "".join(out)
    assert "event.created" in text
    assert len(sse.broker._subs) == 0  # finally cleaned up
