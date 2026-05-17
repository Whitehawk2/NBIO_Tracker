"""
Helpers for translating Python's `zoneinfo` into SQLite-friendly date
arithmetic.

SQLite's `datetime()` function understands `'+N minutes'` /
`'-N minutes'` modifiers, but doesn't know about IANA tz names. We
resolve the current offset in Python (so DST is captured as of the
query moment) and pass it as a parameterised modifier into SQL.

Used by `repo.today_counts` and `repo.daily_totals` to bucket events
by the server-local date instead of UTC (issue #28 finding #1).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def _localised(now: datetime | None, tz_name: str) -> datetime:
    """Resolve `now` (default = current time) into the given tz."""
    tz = ZoneInfo(tz_name)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        # Treat naive as UTC, matching Python's default for naive datetimes.
        return now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    return now.astimezone(tz)


def local_offset_modifier(tz_name: str, now: datetime | None = None) -> str:
    """SQLite datetime() modifier for the current offset of `tz_name`.

    Returns strings like '+60 minutes' / '-300 minutes'. DST is resolved at
    `now`, which defaults to the actual current time — so a long-running
    process picks up DST changes between queries.
    """
    localised = _localised(now, tz_name)
    offset = localised.utcoffset()
    total_minutes = 0 if offset is None else int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    return f"{sign}{abs(total_minutes)} minutes"


def local_today_str(tz_name: str, now: datetime | None = None) -> str:
    """The local-tz date 'YYYY-MM-DD' as of `now`."""
    return _localised(now, tz_name).strftime("%Y-%m-%d")
