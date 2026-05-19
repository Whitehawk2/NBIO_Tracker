"""
app_settings repo functions — runtime-editable singleton config (#6).

`app_settings_read` never returns None (migration 002 seeds id=1).
`app_settings_update` uses `model_dump(exclude_unset=True)` so a PATCH
that only sends `tz` doesn't blank out `notes_md`.
"""

from __future__ import annotations

from nbio.models import AppSettingsUpdate
from nbio.repo import app_settings_read, app_settings_update


def test_app_settings_read_returns_seeded_defaults(conn):
    row = app_settings_read(conn)
    assert row["id"] == 1
    assert row["tz"] is None
    assert row["notes_md"] is None
    assert "updated_at" in row


def test_app_settings_update_persists_tz(conn):
    app_settings_update(conn, AppSettingsUpdate(tz="Europe/London"))
    assert app_settings_read(conn)["tz"] == "Europe/London"


def test_app_settings_update_persists_notes_md(conn):
    app_settings_update(conn, AppSettingsUpdate(notes_md="rclone token expires 2026-12"))
    assert app_settings_read(conn)["notes_md"] == "rclone token expires 2026-12"


def test_app_settings_update_partial_only_touches_supplied_fields(conn):
    """Sending only `tz` must NOT blank out `notes_md`, and vice versa."""
    app_settings_update(conn, AppSettingsUpdate(notes_md="keep me"))
    app_settings_update(conn, AppSettingsUpdate(tz="Asia/Jerusalem"))
    row = app_settings_read(conn)
    assert row["tz"] == "Asia/Jerusalem"
    assert row["notes_md"] == "keep me"


def test_app_settings_update_returns_updated_row(conn):
    out = app_settings_update(conn, AppSettingsUpdate(tz="UTC"))
    assert out["tz"] == "UTC"
    assert out["id"] == 1


def test_app_settings_update_with_no_fields_returns_current_row(conn):
    """An empty PATCH should be a no-op + return the current row."""
    out = app_settings_update(conn, AppSettingsUpdate())
    assert out["id"] == 1
    assert out["tz"] is None


def test_app_settings_update_bumps_updated_at(conn, freezer):
    """`updated_at` ticks on every successful update."""
    freezer.move_to("2026-05-18T12:00:00Z")
    # Seed `before` via a real (non-empty) update under the frozen clock
    # so `updated_at` comes from frozen time, not the SQLite default
    # that ran during fixture init — that default uses real wall clock,
    # which flaked the test once wall-clock-now passed the second
    # move_to. (An empty AppSettingsUpdate() short-circuits before the
    # UPDATE statement, so it doesn't tick `updated_at`.)
    before = app_settings_update(conn, AppSettingsUpdate(tz="UTC"))["updated_at"]
    freezer.move_to("2026-05-18T13:00:00Z")
    after = app_settings_update(conn, AppSettingsUpdate(tz="Asia/Jerusalem"))["updated_at"]
    assert after > before


def test_app_settings_update_rolls_back_on_sql_error(conn):
    """A mid-update failure rolls back the transaction; the row stays intact."""
    import pytest

    from tests.conftest import FailingConn

    app_settings_update(conn, AppSettingsUpdate(tz="UTC"))
    proxy = FailingConn(conn, "UPDATE app_settings")
    with pytest.raises(Exception, match="forced failure"):
        app_settings_update(proxy, AppSettingsUpdate(tz="Asia/Jerusalem"))
    # Original value preserved.
    assert app_settings_read(conn)["tz"] == "UTC"
