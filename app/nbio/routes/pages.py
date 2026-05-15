import sqlite3
from datetime import datetime, timedelta, timezone
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
    diff = datetime.now(timezone.utc) - dt
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


@router.get("/", response_class=HTMLResponse)
def index(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    events = repo.list_events(conn, limit=200)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "baby": repo.baby(conn),
            "today": _today_card(conn),
            "events": events,
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
    totals = repo.daily_totals(conn, days=days)

    # Build last-N-days timeline strips
    now_local = datetime.now().astimezone()
    days_list = []
    all_events = repo.list_events(conn, limit=2000)
    for i in range(7):
        day = (now_local - timedelta(days=i)).date().isoformat()
        days_list.append(
            {
                "day": day,
                "marks": _timeline_marks(all_events, day),
                "is_today": i == 0,
            }
        )

    # 7-day heatmap matrix: 7 days × 24 hours
    heatmap: list[list[int]] = [[0] * 24 for _ in range(7)]
    today = now_local.date()
    for e in all_events:
        try:
            dt = datetime.fromisoformat(e["occurred_at"].replace("Z", "+00:00")).astimezone()
        except ValueError:
            continue
        delta = (today - dt.date()).days
        if 0 <= delta < 7:
            heatmap[delta][dt.hour] += 1
    max_h = max((max(row) for row in heatmap), default=1) or 1

    return templates.TemplateResponse(
        request,
        "reports.html",
        {
            "today": _today_card(conn),
            "totals": totals,
            "days_list": days_list,
            "heatmap": heatmap,
            "heatmap_max": max_h,
            "now_x": (now_local.hour * 3600 + now_local.minute * 60) / 86400.0,
        },
    )
