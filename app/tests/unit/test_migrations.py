"""
Migration runner — apply_pending() contract tests.

The runner watches PRAGMA user_version, finds NNN_*.sql files, runs the
ones whose number is greater than the current version, then sets
user_version to the largest applied version. These tests use a tmp_path
migrations directory so they're decoupled from the real migration files
in nbio/migrations/.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nbio.migrations import _list_migrations, apply_pending, current_version


@pytest.fixture
def empty_db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture
def mig_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    return d


def test_current_version_defaults_to_zero(empty_db):
    assert current_version(empty_db) == 0


def test_apply_pending_no_files_is_noop(empty_db, mig_dir):
    applied = apply_pending(empty_db, mig_dir)
    assert applied == []
    assert current_version(empty_db) == 0


def test_apply_pending_runs_one_migration_and_bumps_version(empty_db, mig_dir):
    (mig_dir / "001_first.sql").write_text("CREATE TABLE foo (x INTEGER);")
    applied = apply_pending(empty_db, mig_dir)
    assert applied == [1]
    assert current_version(empty_db) == 1
    # Migration's effect is visible
    tables = {
        r[0]
        for r in empty_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert "foo" in tables


def test_apply_pending_runs_in_order(empty_db, mig_dir):
    """002 sees the table 001 created; 003 sees 002's modifications."""
    (mig_dir / "001_create.sql").write_text("CREATE TABLE foo (x INTEGER);")
    (mig_dir / "002_alter.sql").write_text("ALTER TABLE foo ADD COLUMN y TEXT;")
    (mig_dir / "003_insert.sql").write_text("INSERT INTO foo (x, y) VALUES (1, 'a');")
    applied = apply_pending(empty_db, mig_dir)
    assert applied == [1, 2, 3]
    assert current_version(empty_db) == 3
    row = empty_db.execute("SELECT x, y FROM foo").fetchone()
    assert row[0] == 1
    assert row[1] == "a"


def test_apply_pending_skips_already_applied(empty_db, mig_dir):
    """Two consecutive calls: second is a no-op."""
    (mig_dir / "001_first.sql").write_text("CREATE TABLE foo (x INTEGER);")
    apply_pending(empty_db, mig_dir)
    applied = apply_pending(empty_db, mig_dir)
    assert applied == []
    assert current_version(empty_db) == 1


def test_apply_pending_partial_skip(empty_db, mig_dir):
    """Starting at user_version=2, only runs 003+."""
    (mig_dir / "001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
    (mig_dir / "002_b.sql").write_text("CREATE TABLE b (x INTEGER);")
    (mig_dir / "003_c.sql").write_text("CREATE TABLE c (x INTEGER);")
    # Pretend 1 and 2 already ran
    empty_db.execute("PRAGMA user_version = 2")
    applied = apply_pending(empty_db, mig_dir)
    assert applied == [3]
    tables = {
        r[0]
        for r in empty_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    # 1 and 2 didn't run, so a and b don't exist; c does
    assert "a" not in tables
    assert "b" not in tables
    assert "c" in tables


def test_apply_pending_ignores_non_migration_files(empty_db, mig_dir):
    """README.md, .DS_Store, foo.sql (without NNN_ prefix) — all skipped."""
    (mig_dir / "README.md").write_text("notes")
    (mig_dir / "no_prefix.sql").write_text("CREATE TABLE not_a_migration (x INTEGER);")
    (mig_dir / "1_too_short.sql").write_text("CREATE TABLE single_digit (x INTEGER);")
    (mig_dir / "01_two_digits.sql").write_text("CREATE TABLE two_digits (x INTEGER);")
    (mig_dir / "001_real.sql").write_text("CREATE TABLE three_digits (x INTEGER);")
    applied = apply_pending(empty_db, mig_dir)
    assert applied == [1]
    tables = {
        r[0]
        for r in empty_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert tables == {"three_digits"}


def test_list_migrations_orders_numerically(mig_dir):
    """10 sorts AFTER 9 (numeric, not lexical)."""
    for i in (1, 2, 9, 10, 11):
        (mig_dir / f"{i:03d}_x.sql").write_text("SELECT 1;")
    found = _list_migrations(mig_dir)
    assert [v for v, _ in found] == [1, 2, 9, 10, 11]


def test_apply_pending_bumps_version_to_last_applied_number(empty_db, mig_dir):
    (mig_dir / "001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
    (mig_dir / "005_b.sql").write_text("CREATE TABLE b (x INTEGER);")
    applied = apply_pending(empty_db, mig_dir)
    assert applied == [1, 5]
    assert current_version(empty_db) == 5
