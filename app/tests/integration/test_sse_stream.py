"""
SSE route end-to-end behaviour.

We avoid httpx.AsyncClient.stream() (it doesn't play well with our SSE
generator's 20s keepalive timeout in-process) and instead call sse_stream()
directly, then iterate the StreamingResponse's body_iterator with our own
asyncio.wait_for so the test can't hang.

This covers: subscribe, header parsing, replay path, disconnect-driven
break, finally cleanup.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from nbio import sse
from nbio.routes.stream import sse_stream


async def _drive(resp, *, max_chunks=3, per_chunk_timeout=1.0):
    """Pull up to N chunks from a StreamingResponse, with a timeout each."""
    out = []
    gen = resp.body_iterator
    for _ in range(max_chunks):
        try:
            chunk = await asyncio.wait_for(gen.__anext__(), timeout=per_chunk_timeout)
        except (TimeoutError, StopAsyncIteration):
            break
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        out.append(chunk)
    # Close the generator so the route's `finally` runs and we unsubscribe.
    await gen.aclose()
    return out


def _mock_request(disconnected=False):
    req = MagicMock()

    async def _is_disc():
        return disconnected

    req.is_disconnected = _is_disc
    return req


@pytest.mark.asyncio
async def test_subscriber_added_then_removed(conn):
    """sse_stream subscribes on entry; cleanup unsubscribes on close."""
    assert len(sse.broker._subs) == 0
    resp = await sse_stream(_mock_request(disconnected=True), last_event_id=None, conn=conn)
    assert len(sse.broker._subs) == 1
    await _drive(resp)
    # close → finally runs → unsubscribed
    assert len(sse.broker._subs) == 0


@pytest.mark.asyncio
async def test_replay_emits_existing_events(conn):
    """With Last-Event-ID, the generator yields replay chunks first."""
    from nbio.models import EventCreate
    from nbio.repo import create_event

    for i in range(3):
        create_event(
            conn,
            EventCreate(
                type="feed",
                occurred_at="2026-05-16T03:00:00.000Z",
                idempotency_key=f"idem-replay-{i:04d}",
                created_by_device="device-test",
            ),
        )

    resp = await sse_stream(_mock_request(disconnected=True), last_event_id="1", conn=conn)
    chunks = await _drive(resp, max_chunks=5)
    text = "".join(chunks)
    # Events with id > 1 (i.e. ids 2 and 3) should appear
    assert "idem-replay-0001" in text
    assert "idem-replay-0002" in text
    # Event id 1 (the first inserted) is NOT in the replay
    assert "idem-replay-0000" not in text


@pytest.mark.asyncio
async def test_invalid_last_event_id_treated_as_zero(conn):
    """Non-integer → last_id=0 → all events replayed."""
    from nbio.models import EventCreate
    from nbio.repo import create_event

    create_event(
        conn,
        EventCreate(
            type="feed",
            occurred_at="2026-05-16T03:00:00.000Z",
            idempotency_key="idem-only-row",
            created_by_device="device-test",
        ),
    )
    resp = await sse_stream(
        _mock_request(disconnected=True), last_event_id="not-a-number", conn=conn
    )
    chunks = await _drive(resp, max_chunks=3)
    assert "idem-only-row" in "".join(chunks)


@pytest.mark.asyncio
async def test_no_last_event_id_no_replay(conn):
    """Without Last-Event-ID, no replay chunks are emitted."""
    from nbio.models import EventCreate
    from nbio.repo import create_event

    create_event(
        conn,
        EventCreate(
            type="feed",
            occurred_at="2026-05-16T03:00:00.000Z",
            idempotency_key="idem-noreplay-1",
            created_by_device="device-test",
        ),
    )
    resp = await sse_stream(_mock_request(disconnected=True), last_event_id=None, conn=conn)
    chunks = await _drive(resp, max_chunks=1, per_chunk_timeout=0.3)
    # No replay → first chunk would be from the live loop (which we don't drive)
    assert "idem-noreplay-1" not in "".join(chunks)


@pytest.mark.asyncio
async def test_publish_after_subscribe_reaches_queue(conn):
    """A publish made after subscribe lands in the subscriber's queue."""
    resp = await sse_stream(_mock_request(disconnected=True), last_event_id=None, conn=conn)
    # Find the subscribed queue
    assert len(sse.broker._subs) == 1
    q = next(iter(sse.broker._subs))
    await sse.broker.publish("event.created", 99, {"id": 99, "type": "feed"})
    msg = q.get_nowait()
    assert msg == ("event.created", 99, {"id": 99, "type": "feed"})
    await _drive(resp)


@pytest.mark.asyncio
async def test_response_has_sse_headers(conn):
    resp = await sse_stream(_mock_request(disconnected=True), last_event_id=None, conn=conn)
    assert resp.media_type == "text/event-stream"
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("x-accel-buffering") == "no"
    await _drive(resp)
