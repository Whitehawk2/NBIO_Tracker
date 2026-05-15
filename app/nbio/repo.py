"""All SQL lives here. Plain functions over sqlite3.Connection."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from .config import settings
from .models import DeviceUpsert, EventCreate, EventPatch

EVENT_COLS = """
    e.id, e.baby_id, e.type, e.occurred_at,
    e.feed_side, e.feed_duration_min, e.poo_quality, e.notes,
    e.idempotency_key, e.created_by_device,
    e.created_at, e.updated_at, e.deleted_at,
    d.color AS actor_color, d.name AS actor_name
"""

EVENT_JOIN = "events e LEFT JOIN devices d ON d.id = e.created_by_device"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _row_to_dict(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def fetch_event(conn: sqlite3.Connection, event_id: int) -> Optional[dict[str, Any]]:
    cur = conn.execute(
        f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} WHERE e.id = ?",
        (event_id,),
    )
    return _row_to_dict(cur.fetchone())


def fetch_event_by_idem(conn: sqlite3.Connection, idem: str) -> Optional[dict[str, Any]]:
    cur = conn.execute(
        f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} WHERE e.idempotency_key = ?",
        (idem,),
    )
    return _row_to_dict(cur.fetchone())


def list_events(
    conn: sqlite3.Connection,
    baby_id: int = 1,
    since: Optional[str] = None,
    limit: int = 200,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    args: list[Any] = [baby_id]
    where = ["e.baby_id = ?"]
    if not include_deleted:
        where.append("e.deleted_at IS NULL")
    if since:
        where.append("e.occurred_at >= ?")
        args.append(since)
    args.append(min(limit, 1000))
    cur = conn.execute(
        f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY e.occurred_at DESC, e.id DESC LIMIT ?",
        args,
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def list_events_since_id(
    conn: sqlite3.Connection,
    last_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    cur = conn.execute(
        f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} "
        "WHERE e.id > ? ORDER BY e.id ASC LIMIT ?",
        (last_id, limit),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def find_duplicate_in_window(
    conn: sqlite3.Connection,
    baby_id: int,
    event_type: str,
    occurred_at: str,
    own_id: int,
) -> Optional[dict[str, Any]]:
    window = settings.dup_window_seconds
    cur = conn.execute(
        """
        SELECT id, occurred_at, created_by_device, type,
               (strftime('%s', occurred_at) - strftime('%s', ?)) AS delta_seconds
        FROM events
        WHERE baby_id = ? AND type = ? AND deleted_at IS NULL AND id != ?
          AND abs(strftime('%s', occurred_at) - strftime('%s', ?)) <= ?
        ORDER BY abs(strftime('%s', occurred_at) - strftime('%s', ?)) ASC
        LIMIT 1
        """,
        (occurred_at, baby_id, event_type, own_id, occurred_at, window, occurred_at),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def create_event(
    conn: sqlite3.Connection,
    payload: EventCreate,
    baby_id: int = 1,
) -> tuple[str, dict[str, Any], Optional[dict[str, Any]]]:
    """
    Returns (status, event_dict, duplicate_of_or_None).
    status ∈ {"created", "created_possible_duplicate", "already_exists"}.
    """
    existing = fetch_event_by_idem(conn, payload.idempotency_key)
    if existing is not None:
        return "already_exists", existing, None

    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            """
            INSERT INTO events (
                baby_id, type, occurred_at,
                feed_side, feed_duration_min, poo_quality, notes,
                idempotency_key, created_by_device
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                baby_id,
                payload.type,
                payload.occurred_at,
                payload.feed_side,
                payload.feed_duration_min,
                payload.poo_quality,
                payload.notes,
                payload.idempotency_key,
                payload.created_by_device,
            ),
        )
        new_id = cur.lastrowid
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        existing = fetch_event_by_idem(conn, payload.idempotency_key)
        if existing is not None:
            return "already_exists", existing, None
        raise

    event = fetch_event(conn, new_id)
    dup = None
    if not payload.skip_dup_check:
        dup = find_duplicate_in_window(
            conn, baby_id, payload.type, payload.occurred_at, new_id
        )
    status = "created_possible_duplicate" if dup else "created"
    return status, event, dup


def patch_event(
    conn: sqlite3.Connection, event_id: int, patch: EventPatch
) -> Optional[dict[str, Any]]:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        return fetch_event(conn, event_id)
    sets = ", ".join(f"{k} = ?" for k in fields)
    args = list(fields.values()) + [_now_iso(), event_id]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"UPDATE events SET {sets}, updated_at = ? WHERE id = ?",
            args,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return fetch_event(conn, event_id)


def soft_delete_event(conn: sqlite3.Connection, event_id: int) -> Optional[dict[str, Any]]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE events SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (_now_iso(), _now_iso(), event_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return fetch_event(conn, event_id)


def undelete_event(conn: sqlite3.Connection, event_id: int) -> Optional[dict[str, Any]]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE events SET deleted_at = NULL, updated_at = ? WHERE id = ?",
            (_now_iso(), event_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return fetch_event(conn, event_id)


def last_feed_side(conn: sqlite3.Connection, baby_id: int = 1) -> Optional[str]:
    row = conn.execute(
        """
        SELECT feed_side FROM events
        WHERE baby_id = ? AND type = 'feed' AND deleted_at IS NULL
        ORDER BY occurred_at DESC, id DESC LIMIT 1
        """,
        (baby_id,),
    ).fetchone()
    return row["feed_side"] if row else None


def last_event_of_each_type(
    conn: sqlite3.Connection, baby_id: int = 1
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for t in ("feed", "wee", "poo"):
        row = conn.execute(
            f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} "
            "WHERE e.baby_id = ? AND e.type = ? AND e.deleted_at IS NULL "
            "ORDER BY e.occurred_at DESC, e.id DESC LIMIT 1",
            (baby_id, t),
        ).fetchone()
        if row:
            out[t] = _row_to_dict(row)
    return out


def today_counts(conn: sqlite3.Connection, baby_id: int = 1) -> dict[str, int]:
    """Counts since local midnight today (UTC-anchored — close enough for v1)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = {"feed": 0, "wee": 0, "poo": 0}
    cur = conn.execute(
        """
        SELECT type, COUNT(*) AS n FROM events
        WHERE baby_id = ? AND deleted_at IS NULL
          AND substr(occurred_at, 1, 10) = ?
        GROUP BY type
        """,
        (baby_id, today),
    )
    for r in cur.fetchall():
        out[r["type"]] = r["n"]
    return out


def daily_totals(
    conn: sqlite3.Connection, baby_id: int = 1, days: int = 14
) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT substr(occurred_at, 1, 10) AS day, type, COUNT(*) AS n,
               AVG(feed_duration_min) AS avg_feed_min
        FROM events
        WHERE baby_id = ? AND deleted_at IS NULL
          AND occurred_at >= date('now', ?)
        GROUP BY day, type
        ORDER BY day DESC
        """,
        (baby_id, f"-{days} days"),
    )
    by_day: dict[str, dict[str, Any]] = {}
    for r in cur.fetchall():
        d = by_day.setdefault(
            r["day"],
            {"day": r["day"], "feed": 0, "wee": 0, "poo": 0, "avg_feed_min": None},
        )
        d[r["type"]] = r["n"]
        if r["type"] == "feed" and r["avg_feed_min"] is not None:
            d["avg_feed_min"] = round(r["avg_feed_min"], 1)
    return list(by_day.values())


def upsert_device(
    conn: sqlite3.Connection, device_id: str, payload: DeviceUpsert
) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO devices (id, name, color, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                color = excluded.color,
                updated_at = excluded.updated_at
            """,
            (device_id, payload.name, payload.color, _now_iso()),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    row = conn.execute(
        "SELECT id, name, color, created_at, updated_at FROM devices WHERE id = ?",
        (device_id,),
    ).fetchone()
    return dict(row)


def list_devices(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, name, color, created_at, updated_at FROM devices ORDER BY created_at ASC"
    )
    return [dict(r) for r in cur.fetchall()]


def baby(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
    r = conn.execute("SELECT id, name, dob FROM babies WHERE id = 1").fetchone()
    return dict(r) if r else None
