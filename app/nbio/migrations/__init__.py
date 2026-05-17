"""
Schema migration runner. Tracks state via `PRAGMA user_version`; each
migration is a `NNN_<slug>.sql` file. Files are executed in numeric
order; ones with a number ≤ current `user_version` are skipped. After
each successful run, `user_version` is bumped to the migration's
number.

Idempotency contract: re-running `apply_pending` on a DB that's already
at the latest version is a no-op (zero queries beyond the PRAGMA read).

This module is called from `db.init_db()` AFTER the `executescript(SCHEMA)`
call so it can fix up existing installs without touching new installs that
already have the latest shape.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent

# Matches NNN_<slug>.sql where NNN is exactly three digits.
_MIGRATION_PATTERN = re.compile(r"^(\d{3})_[A-Za-z0-9_]+\.sql$")


def _list_migrations(migrations_dir: Path | None = None) -> list[tuple[int, Path]]:
    """Return [(version, path), …] sorted by version asc."""
    root = migrations_dir or MIGRATIONS_DIR
    found: list[tuple[int, Path]] = []
    for f in sorted(root.iterdir()):
        if not f.is_file():
            continue
        m = _MIGRATION_PATTERN.match(f.name)
        if m:
            found.append((int(m.group(1)), f))
    found.sort(key=lambda t: t[0])
    return found


def current_version(conn: sqlite3.Connection) -> int:
    """Read `PRAGMA user_version` — defaults to 0 for fresh DBs."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def apply_pending(
    conn: sqlite3.Connection, migrations_dir: Path | None = None
) -> list[int]:
    """
    Apply migrations whose number is greater than the current user_version.
    Returns the list of applied version numbers (empty if up-to-date).
    """
    applied: list[int] = []
    current = current_version(conn)
    for version, path in _list_migrations(migrations_dir):
        if version <= current:
            continue
        sql = path.read_text()
        # Each migration file is responsible for its own transaction
        # boundaries (BEGIN/COMMIT) — executescript handles compound SQL.
        conn.executescript(sql)
        # PRAGMA user_version takes a literal, not a parameter
        conn.execute(f"PRAGMA user_version = {version}")
        applied.append(version)
    return applied
