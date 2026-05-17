"""
Replay cap behaviour. Drives sse_stream() directly with controlled
sse_replay_cap settings.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from nbio.routes.stream import sse_stream


def _mock_request():
    req = MagicMock()

    async def _is_disc():
        return True  # break out of the live loop immediately

    req.is_disconnected = _is_disc
    return req


async def _drive(resp, *, max_chunks=10, per_chunk_timeout=1.0):
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
    await gen.aclose()
    return out


@pytest.mark.asyncio
async def test_replay_caps_at_sse_replay_cap(conn, monkeypatch):
    """sse_replay_cap=2 → at most 2 since-id rows are replayed."""
    from nbio import config
    from nbio.models import EventCreate
    from nbio.repo import create_event

    monkeypatch.setattr(config.settings, "sse_replay_cap", 2)
    for i in range(5):
        create_event(
            conn,
            EventCreate(
                type="breast",
                occurred_at="2026-05-16T03:00:00.000Z",
                idempotency_key=f"idem-cap-{i:04d}",
                created_by_device="device-test",
            ),
        )

    resp = await sse_stream(_mock_request(), last_event_id="0", conn=conn)
    chunks = await _drive(resp, max_chunks=10)
    text = "".join(chunks)
    # First two events replayed
    assert "idem-cap-0000" in text
    assert "idem-cap-0001" in text
    # Beyond the cap
    assert "idem-cap-0004" not in text


@pytest.mark.asyncio
async def test_replay_with_huge_last_event_id_emits_nothing(conn):
    """last_event_id larger than any existing id → empty replay."""
    from nbio.models import EventCreate
    from nbio.repo import create_event

    create_event(
        conn,
        EventCreate(
            type="breast",
            occurred_at="2026-05-16T03:00:00.000Z",
            idempotency_key="idem-anyone",
            created_by_device="device-test",
        ),
    )
    resp = await sse_stream(_mock_request(), last_event_id="99999", conn=conn)
    chunks = await _drive(resp, max_chunks=2, per_chunk_timeout=0.3)
    assert "idem-anyone" not in "".join(chunks)
