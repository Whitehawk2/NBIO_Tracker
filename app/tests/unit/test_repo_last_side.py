"""last_feed_side — server-side smart-default for the feed modal."""

from nbio.models import EventCreate
from nbio.repo import create_event, last_feed_side, soft_delete_event


def _feed(idem, occurred_at, side):
    """Pads the idem so even short like 'i1' satisfies min_length=8."""
    return EventCreate(
        type="feed",
        occurred_at=occurred_at,
        feed_side=side,
        idempotency_key=f"idem-{idem}-pad",
        created_by_device="device-1",
    )


def test_returns_none_when_no_feeds(conn):
    assert last_feed_side(conn) is None


def test_returns_only_feed_side(conn):
    create_event(conn, _feed("i1", "2026-05-16T03:00:00.000Z", "L"))
    assert last_feed_side(conn) == "L"


def test_returns_most_recent_feed_side(conn):
    create_event(conn, _feed("i1", "2026-05-16T03:00:00.000Z", "L"))
    create_event(conn, _feed("i2", "2026-05-16T05:00:00.000Z", "R"))
    create_event(conn, _feed("i3", "2026-05-16T04:00:00.000Z", "both"))
    assert last_feed_side(conn) == "R"  # 05:00 wins


def test_ignores_deleted(conn):
    create_event(conn, _feed("i1", "2026-05-16T03:00:00.000Z", "L"))
    _, second, _ = create_event(conn, _feed("i2", "2026-05-16T05:00:00.000Z", "R"))
    soft_delete_event(conn, second["id"])
    assert last_feed_side(conn) == "L"


def test_ignores_non_feed_events(conn):
    from nbio.models import EventCreate

    create_event(conn, _feed("i1", "2026-05-16T03:00:00.000Z", "L"))
    create_event(
        conn,
        EventCreate(
            type="wee",
            occurred_at="2026-05-16T05:00:00.000Z",
            idempotency_key="idem-i2-pad",
            created_by_device="device-1",
        ),
    )
    assert last_feed_side(conn) == "L"


def test_feed_with_null_side_returns_null(conn):
    """A feed logged without side recorded propagates None."""
    create_event(
        conn,
        EventCreate(
            type="feed",
            occurred_at="2026-05-16T03:00:00.000Z",
            idempotency_key="idem-i1-pad",
            created_by_device="device-1",
            # feed_side omitted
        ),
    )
    assert last_feed_side(conn) is None


def test_tie_broken_by_id(conn):
    """Same occurred_at → ORDER BY id DESC picks the later insertion."""
    same = "2026-05-16T03:00:00.000Z"
    create_event(conn, _feed("tie1", same, "L"))
    create_event(conn, _feed("tie2", same, "R"))
    assert last_feed_side(conn) == "R"
