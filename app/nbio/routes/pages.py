import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import repo
from ..db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _relative(occurred_at: str) -> str:
    """Return e.g. '2h 14m ago'. Assumes ISO-8601 UTC."""
    try:
        dt = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    diff = datetime.now(UTC) - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        h, m = divmod(secs // 60, 60)
        return f"{h}h {m:02d}m ago" if m else f"{h}h ago"
    d = secs // 86400
    return f"{d}d ago"


def _local_hhmm(occurred_at: str) -> str:
    try:
        dt = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    # Render in the server-local tz (set via TZ env in container)
    return dt.astimezone().strftime("%H:%M")


templates.env.filters["relative"] = _relative
templates.env.filters["hhmm"] = _local_hhmm


def _today_card(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "counts": repo.today_counts(conn),
        "last": repo.last_event_of_each_type(conn),
    }


_WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTH_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _day_label(d: date, today: date) -> str:
    delta = (today - d).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return f"{_WEEKDAY_SHORT[d.weekday()]} {d.day} {_MONTH_SHORT[d.month - 1]}"


def _group_events_by_local_day(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group events into [{day, label, events:[...]}] using server-local timezone."""
    today_local = datetime.now().astimezone().date()
    groups: dict[str, dict[str, Any]] = {}
    for e in events:
        try:
            dt_local = datetime.fromisoformat(e["occurred_at"].replace("Z", "+00:00")).astimezone()
        except ValueError:
            continue
        d = dt_local.date()
        key = d.isoformat()
        g = groups.get(key)
        if g is None:
            g = {"day": key, "label": _day_label(d, today_local), "_date": d, "events": []}
            groups[key] = g
        g["events"].append(e)
    return [
        {k: v for k, v in g.items() if k != "_date"}
        for g in sorted(groups.values(), key=lambda g: g["_date"], reverse=True)
    ]


def _last_days_rows(totals: list[dict[str, Any]], n: int = 3) -> list[dict[str, Any]]:
    """Pad the last N local days regardless of whether events were logged."""
    today_local = datetime.now().astimezone().date()
    by_day = {row["day"]: row for row in totals}
    rows: list[dict[str, Any]] = []
    for i in range(n):
        d = today_local - timedelta(days=i)
        key = d.isoformat()
        row = by_day.get(key, {"day": key, "feed": 0, "wee": 0, "poo": 0})
        rows.append(
            {
                "day": key,
                "label": _day_label(d, today_local),
                "feed": row.get("feed", 0),
                "wee": row.get("wee", 0),
                "poo": row.get("poo", 0),
            }
        )
    return rows


@router.get("/", response_class=HTMLResponse)
def index(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    # Pull a window large enough to cover the last 3 local days, then filter.
    now_local = datetime.now().astimezone()
    cutoff_local_day = (now_local - timedelta(days=2)).date()
    raw_events = repo.list_events(conn, limit=500)
    events = [
        e
        for e in raw_events
        if datetime.fromisoformat(e["occurred_at"].replace("Z", "+00:00")).astimezone().date()
        >= cutoff_local_day
    ]
    grouped_events = _group_events_by_local_day(events)
    last_days = _last_days_rows(repo.daily_totals(conn, days=4), n=3)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "baby": repo.baby(conn),
            "today": _today_card(conn),
            "events": events,
            "grouped_events": grouped_events,
            "last_days": last_days,
            "devices": repo.list_devices(conn),
        },
    )


def _timeline_marks(events: list[dict[str, Any]], day_iso: str) -> list[dict[str, Any]]:
    """Compute x-positions (0..1) for events occurring on day_iso (UTC date)."""
    marks: list[dict[str, Any]] = []
    for e in events:
        if not e["occurred_at"].startswith(day_iso):
            continue
        try:
            dt = datetime.fromisoformat(e["occurred_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        local = dt.astimezone()
        seconds = local.hour * 3600 + local.minute * 60 + local.second
        marks.append({"x": seconds / 86400.0, "type": e["type"]})
    return marks


@router.get("/reports", response_class=HTMLResponse)
def reports(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    days = 14
    today_local = datetime.now().astimezone().date()
    totals = repo.daily_totals(conn, days=days)
    for row in totals:
        try:
            d = datetime.strptime(row["day"], "%Y-%m-%d").date()
            row["label"] = _day_label(d, today_local)
        except (KeyError, ValueError):
            row["label"] = row.get("day", "")

    # Build last-N-days timeline strips
    now_local = datetime.now().astimezone()
    today = now_local.date()
    days_list = []
    all_events = repo.list_events(conn, limit=2000)
    for i in range(7):
        d = (now_local - timedelta(days=i)).date()
        days_list.append(
            {
                "day": d.isoformat(),
                "label": _day_label(d, today),
                "marks": _timeline_marks(all_events, d.isoformat()),
                "is_today": i == 0,
            }
        )

    # 7-day heatmap matrix: 7 days × 24 hours (rows top→bottom = today, -1, -2, …)
    heatmap: list[list[int]] = [[0] * 24 for _ in range(7)]
    for e in all_events:
        try:
            dt = datetime.fromisoformat(e["occurred_at"].replace("Z", "+00:00")).astimezone()
        except ValueError:
            continue
        delta = (today - dt.date()).days
        if 0 <= delta < 7:
            heatmap[delta][dt.hour] += 1
    max_h = max((max(row) for row in heatmap), default=1) or 1
    heatmap_day_labels = [_day_label(today - timedelta(days=i), today) for i in range(7)]

    return templates.TemplateResponse(
        request,
        "reports.html",
        {
            "today": _today_card(conn),
            "totals": totals,
            "days_list": days_list,
            "heatmap": heatmap,
            "heatmap_max": max_h,
            "heatmap_day_labels": heatmap_day_labels,
            "now_x": (now_local.hour * 3600 + now_local.minute * 60) / 86400.0,
        },
    )
