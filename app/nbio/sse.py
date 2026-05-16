"""In-process SSE broker. One asyncio.Queue per connected client."""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any


class Broker:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    async def publish(self, event_name: str, event_id: int, payload: dict[str, Any]) -> None:
        msg = (event_name, event_id, payload)
        for q in list(self._subs):
            # slow consumer → drop; client catches up via Last-Event-ID on reconnect
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(msg)


broker = Broker()


def format_sse(event_name: str, event_id: int, data: dict[str, Any]) -> str:
    return (
        f"id: {event_id}\nevent: {event_name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
    )


async def stream(
    queue: asyncio.Queue,
    keepalive_seconds: int = 20,
) -> AsyncIterator[str]:
    """Yield SSE-formatted strings from queue, with periodic keepalive comments."""
    while True:
        try:
            event_name, event_id, payload = await asyncio.wait_for(
                queue.get(), timeout=keepalive_seconds
            )
            yield format_sse(event_name, event_id, payload)
        except TimeoutError:
            yield ": ping\n\n"
