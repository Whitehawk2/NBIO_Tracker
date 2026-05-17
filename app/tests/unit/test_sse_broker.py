"""SSE broker primitives: subscribe / unsubscribe / publish / queue-full drop."""

import asyncio

import pytest

from nbio.sse import Broker, format_sse, stream


@pytest.fixture
def broker():
    return Broker()


@pytest.mark.asyncio
async def test_subscribe_returns_queue(broker):
    q = broker.subscribe()
    assert isinstance(q, asyncio.Queue)
    assert q in broker._subs


@pytest.mark.asyncio
async def test_unsubscribe_removes(broker):
    q = broker.subscribe()
    broker.unsubscribe(q)
    assert q not in broker._subs


@pytest.mark.asyncio
async def test_unsubscribe_unknown_is_silent(broker):
    """Discarding a never-subscribed queue is a no-op (no KeyError)."""
    fake = asyncio.Queue()
    broker.unsubscribe(fake)  # must not raise


@pytest.mark.asyncio
async def test_publish_fans_out_to_all_subscribers(broker):
    q1 = broker.subscribe()
    q2 = broker.subscribe()
    await broker.publish("event.x", 1, {"k": "v"})
    assert q1.get_nowait() == ("event.x", 1, {"k": "v"})
    assert q2.get_nowait() == ("event.x", 1, {"k": "v"})


@pytest.mark.asyncio
async def test_publish_drops_when_full(broker):
    """A subscriber whose queue is full silently drops; no exception."""
    q = broker.subscribe()
    # Fill the queue exactly to capacity
    for i in range(q.maxsize):
        q.put_nowait(("x", i, {}))
    assert q.full()
    await broker.publish("event.x", 999, {"new": True})
    # Queue still at capacity, no exception bubbled
    assert q.qsize() == q.maxsize


def test_format_sse_shape():
    out = format_sse("event.created", 42, {"id": 42, "type": "breast"})
    # id / event / data lines + blank terminator
    assert out.startswith("id: 42\n")
    assert "\nevent: event.created\n" in out
    assert "\ndata: " in out
    assert out.endswith("\n\n")


@pytest.mark.asyncio
async def test_stream_yields_published_events():
    q = asyncio.Queue()
    await q.put(("event.created", 7, {"x": 1}))

    gen = stream(q, keepalive_seconds=10)
    chunk = await gen.__anext__()
    await gen.aclose()
    assert chunk.startswith("id: 7\n")
    assert "event.created" in chunk


@pytest.mark.asyncio
async def test_stream_emits_keepalive_on_timeout():
    """When the queue is silent past keepalive, yield ': ping\\n\\n'."""
    q = asyncio.Queue()
    gen = stream(q, keepalive_seconds=0)
    chunk = await gen.__anext__()
    await gen.aclose()
    assert chunk == ": ping\n\n"
