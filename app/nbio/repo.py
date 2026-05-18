"""All SQL lives here. Plain functions over sqlite3.Connection."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from .config import settings
from .models import (
    AppSettingsUpdate,
    BabyUpdate,
    DeviceUpsert,
    EventCreate,
    EventPatch,
)

EVENT_COLS = """
    e.id, e.baby_id, e.type, e.occurred_at,
    e.feed_side, e.feed_duration_min, e.poo_quality, e.notes,
    e.formula_brand, e.formula_volume_ml,
    e.idempotency_key, e.created_by_device,
    e.created_at, e.updated_at, e.deleted_at,
    d.color AS actor_color, d.name AS actor_name
"""

EVENT_JOIN = "events e LEFT JOIN devices d ON d.id = e.created_by_device"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}  # noqa: SIM118 — sqlite3.Row needs .keys()


def fetch_event(conn: sqlite3.Connection, event_id: int) -> dict[str, Any] | None:
    cur = conn.execute(
        f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} WHERE e.id = ?",
        (event_id,),
    )
    return _row_to_dict(cur.fetchone())


def fetch_event_by_idem(conn: sqlite3.Connection, idem: str) -> dict[str, Any] | None:
    cur = conn.execute(
        f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} WHERE e.idempotency_key = ?",
        (idem,),
    )
    return _row_to_dict(cur.fetchone())


def list_events(
    conn: sqlite3.Connection,
    baby_id: int = 1,
    since: str | None = None,
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
    return [d for d in (_row_to_dict(r) for r in cur.fetchall()) if d is not None]


def list_events_since_id(
    conn: sqlite3.Connection,
    last_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    cur = conn.execute(
        f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} WHERE e.id > ? ORDER BY e.id ASC LIMIT ?",
        (last_id, limit),
    )
    return [d for d in (_row_to_dict(r) for r in cur.fetchall()) if d is not None]


def find_duplicate_in_window(
    conn: sqlite3.Connection,
    baby_id: int,
    event_type: str,
    occurred_at: str,
    own_id: int,
) -> dict[str, Any] | None:
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
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """
    Returns (status, event_dict, duplicate_of_or_None).
    status ∈ {"created", "created_possible_duplicate", "already_exists"}.
    """
    existing = fetch_event_by_idem(conn, payload.idempotency_key)
    if existing is not None:
        return "already_exists", existing, None

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Set created_at / updated_at explicitly via Python so the precision
        # is consistent with patch/delete (`_now_iso()` writes microseconds;
        # the schema DEFAULT writes milliseconds, which makes string
        # comparison of created_at vs updated_at non-monotonic). Also lets
        # tests pin time via freezer.
        now = _now_iso()
        cur = conn.execute(
            """
            INSERT INTO events (
                baby_id, type, occurred_at,
                feed_side, feed_duration_min, poo_quality, notes,
                formula_brand, formula_volume_ml,
                idempotency_key, created_by_device,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                baby_id,
                payload.type,
                payload.occurred_at,
                payload.feed_side,
                payload.feed_duration_min,
                payload.poo_quality,
                payload.notes,
                payload.formula_brand,
                payload.formula_volume_ml,
                payload.idempotency_key,
                payload.created_by_device,
                now,
                now,
            ),
        )
        new_id = cur.lastrowid
        assert new_id is not None  # sqlite returns the inserted rowid for INSERT
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        existing = fetch_event_by_idem(conn, payload.idempotency_key)
        if existing is not None:
            return "already_exists", existing, None
        raise

    event = fetch_event(conn, new_id)
    assert event is not None  # we just inserted it
    dup = None
    if not payload.skip_dup_check:
        dup = find_duplicate_in_window(conn, baby_id, payload.type, payload.occurred_at, new_id)
    status = "created_possible_duplicate" if dup else "created"
    return status, event, dup


def patch_event(
    conn: sqlite3.Connection, event_id: int, patch: EventPatch
) -> dict[str, Any] | None:
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


def soft_delete_event(conn: sqlite3.Connection, event_id: int) -> dict[str, Any] | None:
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


def undelete_event(conn: sqlite3.Connection, event_id: int) -> dict[str, Any] | None:
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


def last_feed_side(conn: sqlite3.Connection, baby_id: int = 1) -> str | None:
    """Most recent breast-feed side. Formula feeds have no side and are skipped."""
    row = conn.execute(
        """
        SELECT feed_side FROM events
        WHERE baby_id = ? AND type = 'breast' AND deleted_at IS NULL
        ORDER BY occurred_at DESC, id DESC LIMIT 1
        """,
        (baby_id,),
    ).fetchone()
    return row["feed_side"] if row else None


def last_feed_method(conn: sqlite3.Connection, baby_id: int = 1) -> dict[str, Any] | None:
    """
    Most recent breast OR formula event with enough detail for the modal
    to pre-fill smart defaults. Returns None when there are no feeds.
    Soft-deleted rows are skipped.
    """
    row = conn.execute(
        f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} "
        "WHERE e.baby_id = ? AND e.type IN ('breast', 'formula') AND e.deleted_at IS NULL "
        "ORDER BY e.occurred_at DESC, e.id DESC LIMIT 1",
        (baby_id,),
    ).fetchone()
    return _row_to_dict(row)


def last_event_of_each_type(
    conn: sqlite3.Connection, baby_id: int = 1
) -> dict[str, dict[str, Any]]:
    """
    Most recent event per consumer-facing category. Returns up to five
    keys: `breast`, `formula`, `feed` (the most recent of breast OR
    formula — used by the combined today-card "last feed" line), `wee`,
    `poo`. Keys for types with no logged event are absent.

    The separate per-type breast/formula keys exist because each tile
    shows its own "last X ago" — driving them off the combined `feed`
    key alone makes whichever tile isn't the most-recent feed type
    silently show "no recent" (production bug, May 2026).
    """
    out: dict[str, dict[str, Any]] = {}

    for t in ("breast", "formula", "wee", "poo", "vitd"):
        row = conn.execute(
            f"SELECT {EVENT_COLS} FROM {EVENT_JOIN} "
            "WHERE e.baby_id = ? AND e.type = ? AND e.deleted_at IS NULL "
            "ORDER BY e.occurred_at DESC, e.id DESC LIMIT 1",
            (baby_id, t),
        ).fetchone()
        if row:
            d = _row_to_dict(row)
            assert d is not None
            out[t] = d

    # Combined feed = the more recent of breast or formula. Compared by
    # `occurred_at` directly — ISO-8601 UTC strings sort lexically the
    # same way as their datetimes.
    breast = out.get("breast")
    formula = out.get("formula")
    if breast and formula:
        out["feed"] = breast if breast["occurred_at"] >= formula["occurred_at"] else formula
    elif breast:
        out["feed"] = breast
    elif formula:
        out["feed"] = formula
    return out


def today_counts(conn: sqlite3.Connection, baby_id: int = 1) -> dict[str, int]:
    """
    Counts since local midnight today, in the server-configured tz.
    Breast + formula are combined under "feed" per the today_card contract.
    Total formula intake (cc/ml) for today is exposed as `formula_ml` —
    it's a glance metric on its own (a parent wants to know "did baby
    drink enough today?" without doing mental arithmetic).

    Local-tz bucketing avoids the issue #28 #1 bug where late-evening
    local entries appeared in yesterday's UTC bucket.
    """
    from .tz import local_offset_modifier, local_today_str

    offset = local_offset_modifier(settings.tz)
    today = local_today_str(settings.tz)
    out = {"feed": 0, "wee": 0, "poo": 0, "vitd": 0, "formula_ml": 0}
    cur = conn.execute(
        """
        SELECT type,
               COUNT(*) AS n,
               COALESCE(SUM(formula_volume_ml), 0) AS volume_ml
        FROM events
        WHERE baby_id = ? AND deleted_at IS NULL
          AND substr(datetime(occurred_at, ?), 1, 10) = ?
        GROUP BY type
        """,
        (baby_id, offset, today),
    )
    for r in cur.fetchall():
        if r["type"] in ("breast", "formula"):
            out["feed"] += r["n"]
        else:
            out[r["type"]] = r["n"]
        if r["type"] == "formula":
            out["formula_ml"] += int(r["volume_ml"] or 0)
    return out


def daily_totals(
    conn: sqlite3.Connection, baby_id: int = 1, days: int = 14
) -> list[dict[str, Any]]:
    """
    Per-day totals, bucketed by the server-configured local tz date.
    The reports page wants formula vs breast broken out separately;
    the today_card wants them combined. We expose BOTH:
      row["breast"], row["formula"]  — separate counts
      row["feed"]                    — convenience sum for combined views

    Local-tz bucketing (fixed via SQLite `datetime(occurred_at, ?)` with
    the offset computed in Python) avoids the issue #28 #1 bug where
    late-evening local entries appeared in yesterday's bucket.
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from zoneinfo import ZoneInfo

    from .tz import local_offset_modifier

    offset = local_offset_modifier(settings.tz)
    # Cutoff is also local-tz: `days` days back from local today.
    local_now = _dt.now(ZoneInfo(settings.tz))
    cutoff = (local_now - _td(days=days)).strftime("%Y-%m-%d")
    cur = conn.execute(
        """
        SELECT substr(datetime(occurred_at, ?), 1, 10) AS day,
               type,
               COUNT(*) AS n,
               AVG(feed_duration_min) AS avg_feed_min,
               COALESCE(SUM(formula_volume_ml), 0) AS volume_ml
        FROM events
        WHERE baby_id = ? AND deleted_at IS NULL
          AND substr(datetime(occurred_at, ?), 1, 10) >= ?
        GROUP BY day, type
        ORDER BY day DESC
        """,
        (offset, baby_id, offset, cutoff),
    )
    by_day: dict[str, dict[str, Any]] = {}
    for r in cur.fetchall():
        d = by_day.setdefault(
            r["day"],
            {
                "day": r["day"],
                "breast": 0,
                "formula": 0,
                "feed": 0,
                "wee": 0,
                "poo": 0,
                "vitd": 0,
                "formula_ml": 0,
                "avg_feed_min": None,
            },
        )
        d[r["type"]] = r["n"]
        if r["type"] == "formula":
            d["formula_ml"] += int(r["volume_ml"] or 0)
        if r["type"] in ("breast", "formula"):
            d["feed"] = d["breast"] + d["formula"]
        if r["type"] == "breast" and r["avg_feed_min"] is not None:
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


def baby(conn: sqlite3.Connection) -> dict[str, Any] | None:
    r = conn.execute("SELECT id, name, dob FROM babies WHERE id = 1").fetchone()
    return dict(r) if r else None


def update_baby(conn: sqlite3.Connection, patch: BabyUpdate) -> dict[str, Any]:
    """PATCH the singleton babies (id=1) row. Returns the updated row."""
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        out = baby(conn)
        assert out is not None  # seeded at init_db
        return out
    sets = ", ".join(f"{k} = ?" for k in fields)
    args = [*fields.values(), 1]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"UPDATE babies SET {sets} WHERE id = ?", args)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    out = baby(conn)
    assert out is not None
    return out


def app_settings_read(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the singleton app_settings row. Never None — seeded by migration 002."""
    r = conn.execute(
        "SELECT id, tz, notes_md, updated_at FROM app_settings WHERE id = 1"
    ).fetchone()
    assert r is not None, "app_settings id=1 missing — migration 002 didn't run?"
    return dict(r)


def app_settings_update(conn: sqlite3.Connection, patch: AppSettingsUpdate) -> dict[str, Any]:
    """PATCH the singleton app_settings (id=1) row. Returns the updated row."""
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        return app_settings_read(conn)
    sets = ", ".join(f"{k} = ?" for k in fields)
    args = [*fields.values(), _now_iso(), 1]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"UPDATE app_settings SET {sets}, updated_at = ? WHERE id = ?",
            args,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return app_settings_read(conn)
