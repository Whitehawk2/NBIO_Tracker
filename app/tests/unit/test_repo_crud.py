"""repo.py — create/fetch/list/patch/delete/undelete happy paths."""

from nbio.models import EventCreate, EventPatch
from nbio.repo import (
    baby,
    create_event,
    fetch_event,
    fetch_event_by_idem,
    list_events,
    list_events_since_id,
    patch_event,
    soft_delete_event,
    undelete_event,
)

ISO = "2026-05-16T03:00:00.000Z"


def _payload(**over):
    base = {
        "type": "feed",
        "occurred_at": ISO,
        "idempotency_key": "idem-0001",
        "created_by_device": "device-1",
    }
    base.update(over)
    return EventCreate(**base)


def test_create_returns_created(conn):
    status, event, dup = create_event(conn, _payload())
    assert status == "created"
    assert dup is None
    assert event["id"] == 1
    assert event["type"] == "feed"
    assert event["occurred_at"] == ISO
    assert event["created_by_device"] == "device-1"


def test_fetch_event_returns_dict(conn):
    _, event, _ = create_event(conn, _payload())
    fetched = fetch_event(conn, event["id"])
    assert fetched is not None
    assert fetched["id"] == event["id"]


def test_fetch_event_missing_returns_none(conn):
    assert fetch_event(conn, 999) is None


def test_fetch_event_by_idem(conn):
    create_event(conn, _payload(idempotency_key="idem-fetch"))
    e = fetch_event_by_idem(conn, "idem-fetch")
    assert e is not None
    assert e["idempotency_key"] == "idem-fetch"


def test_fetch_event_by_idem_missing(conn):
    assert fetch_event_by_idem(conn, "nope-not-here") is None


def test_list_events_orders_newest_first(conn):
    create_event(
        conn, _payload(occurred_at="2026-05-16T01:00:00.000Z", idempotency_key="idem-i1-pad")
    )
    create_event(
        conn, _payload(occurred_at="2026-05-16T03:00:00.000Z", idempotency_key="idem-i2-pad")
    )
    create_event(
        conn, _payload(occurred_at="2026-05-16T02:00:00.000Z", idempotency_key="idem-i3-pad")
    )
    events = list_events(conn)
    assert [e["occurred_at"] for e in events] == [
        "2026-05-16T03:00:00.000Z",
        "2026-05-16T02:00:00.000Z",
        "2026-05-16T01:00:00.000Z",
    ]


def test_list_events_filters_deleted_by_default(conn):
    _, e, _ = create_event(conn, _payload())
    soft_delete_event(conn, e["id"])
    assert list_events(conn) == []
    assert len(list_events(conn, include_deleted=True)) == 1


def test_list_events_since_filter(conn):
    create_event(
        conn, _payload(occurred_at="2026-05-16T01:00:00.000Z", idempotency_key="idem-i1-pad")
    )
    create_event(
        conn, _payload(occurred_at="2026-05-16T03:00:00.000Z", idempotency_key="idem-i2-pad")
    )
    events = list_events(conn, since="2026-05-16T02:00:00.000Z")
    assert len(events) == 1
    assert events[0]["occurred_at"] == "2026-05-16T03:00:00.000Z"


def test_list_events_limit_capped_at_1000(conn):
    """limit > 1000 silently clamps."""
    for i in range(5):
        create_event(conn, _payload(idempotency_key=f"idem-i{i:04d}"))
    events = list_events(conn, limit=99999)
    assert len(events) == 5  # cap doesn't manufacture rows


def test_list_events_since_id(conn):
    _, e1, _ = create_event(conn, _payload(idempotency_key="idem-i1-pad"))
    _, e2, _ = create_event(conn, _payload(idempotency_key="idem-i2-pad"))
    _, e3, _ = create_event(conn, _payload(idempotency_key="idem-i3-pad"))
    rows = list_events_since_id(conn, last_id=e1["id"], limit=10)
    assert [r["id"] for r in rows] == [e2["id"], e3["id"]]


def test_list_events_since_id_respects_limit(conn):
    for i in range(5):
        create_event(conn, _payload(idempotency_key=f"idem-i{i:04d}"))
    assert len(list_events_since_id(conn, last_id=0, limit=2)) == 2


def test_patch_event_partial(conn):
    _, event, _ = create_event(conn, _payload())
    patched = patch_event(conn, event["id"], EventPatch(feed_side="R"))
    assert patched is not None
    assert patched["feed_side"] == "R"
    # other fields preserved
    assert patched["occurred_at"] == ISO


def test_patch_event_bumps_updated_at(conn):
    _, event, _ = create_event(conn, _payload())
    original_updated = event["updated_at"]
    patched = patch_event(conn, event["id"], EventPatch(notes="late"))
    assert patched["updated_at"] != original_updated


def test_patch_event_empty_returns_existing(conn):
    """Empty patch (no set fields) is a no-op fetch."""
    _, event, _ = create_event(conn, _payload())
    patched = patch_event(conn, event["id"], EventPatch())
    assert patched is not None
    assert patched["id"] == event["id"]


def test_patch_event_missing_returns_none(conn):
    """Patching a non-existent id returns None (route layer 404s on this)."""
    out = patch_event(conn, 999, EventPatch(notes="x"))
    assert out is None


def test_soft_delete_sets_deleted_at(conn):
    _, event, _ = create_event(conn, _payload())
    deleted = soft_delete_event(conn, event["id"])
    assert deleted is not None
    assert deleted["deleted_at"] is not None


def test_soft_delete_idempotent(conn):
    """Soft-delete on an already-deleted row leaves deleted_at unchanged."""
    _, event, _ = create_event(conn, _payload())
    first = soft_delete_event(conn, event["id"])
    second = soft_delete_event(conn, event["id"])
    assert first["deleted_at"] == second["deleted_at"]


def test_undelete_clears_deleted_at(conn):
    _, event, _ = create_event(conn, _payload())
    soft_delete_event(conn, event["id"])
    restored = undelete_event(conn, event["id"])
    assert restored is not None
    assert restored["deleted_at"] is None


def test_undelete_missing_returns_none(conn):
    assert undelete_event(conn, 999) is None


def test_baby_seeded(conn):
    """conftest seeds baby id=1 with name 'Test Baby'."""
    b = baby(conn)
    assert b is not None
    assert b["id"] == 1
    assert b["name"] == "Test Baby"


def test_baby_returns_none_when_empty(tmp_db_conn):
    """If no baby row, baby() returns None."""
    tmp_db_conn.execute("DELETE FROM babies")
    assert baby(tmp_db_conn) is None


def test_event_join_includes_actor_color(conn):
    """When the creating device exists in `devices`, its color joins through."""
    from nbio.models import DeviceUpsert
    from nbio.repo import upsert_device

    upsert_device(conn, "device-1", DeviceUpsert(name="Mum", color="#aabbcc"))
    _, event, _ = create_event(conn, _payload())
    assert event["actor_color"] == "#aabbcc"
    assert event["actor_name"] == "Mum"
