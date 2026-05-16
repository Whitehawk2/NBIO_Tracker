"""db.connect / init_db — PRAGMAs, idempotency, nested dir creation."""

import sqlite3
from pathlib import Path


def test_connect_applies_pragmas(monkeypatch, tmp_path):
    """connect() should set WAL, foreign_keys, busy_timeout."""
    from nbio import config, db

    monkeypatch.setattr(config.settings, "db_path", str(tmp_path / "p.db"))
    conn = db.connect()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_init_db_creates_parent_dirs(monkeypatch, tmp_path):
    """`Path.parent.mkdir(parents=True)` covers a deeply-nested path."""
    from nbio import config, db

    nested = tmp_path / "a" / "b" / "c" / "app.db"
    monkeypatch.setattr(config.settings, "db_path", str(nested))
    db.init_db()
    assert nested.exists()
    assert nested.parent.is_dir()


def test_init_db_seeds_baby_first_time(monkeypatch, tmp_path):
    from nbio import config, db

    monkeypatch.setattr(config.settings, "db_path", str(tmp_path / "p.db"))
    monkeypatch.setattr(config.settings, "baby_name", "Ada")
    db.init_db()
    conn = db.connect()
    try:
        row = conn.execute("SELECT id, name FROM babies WHERE id=1").fetchone()
        assert row["name"] == "Ada"
    finally:
        conn.close()


def test_init_db_idempotent_does_not_replace_baby(monkeypatch, tmp_path):
    """Re-running init_db with a different baby_name keeps the original row."""
    from nbio import config, db

    p = tmp_path / "p.db"
    monkeypatch.setattr(config.settings, "db_path", str(p))
    monkeypatch.setattr(config.settings, "baby_name", "Ada")
    db.init_db()
    monkeypatch.setattr(config.settings, "baby_name", "Grace")
    db.init_db()
    conn = db.connect()
    try:
        row = conn.execute("SELECT name FROM babies WHERE id=1").fetchone()
        assert row["name"] == "Ada"  # first-write wins
    finally:
        conn.close()


def test_get_conn_yields_and_closes(monkeypatch, tmp_path):
    """get_conn is a generator dependency; exhausting it should close the conn."""
    from nbio import config, db

    monkeypatch.setattr(config.settings, "db_path", str(tmp_path / "p.db"))
    db.init_db()
    gen = db.get_conn()
    conn = next(gen)
    assert conn.execute("SELECT 1").fetchone()[0] == 1
    # Drive the generator to completion → triggers conn.close()
    for _ in gen:
        pass
    # After close, executing again raises ProgrammingError
    import pytest

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_schema_creates_expected_tables(tmp_path: Path):
    """Sanity check: schema executes cleanly on an empty DB."""
    from nbio.db import SCHEMA

    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    names = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert names == {"babies", "devices", "events"}
    conn.close()
