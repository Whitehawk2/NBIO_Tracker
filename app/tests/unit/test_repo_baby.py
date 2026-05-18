"""
update_baby — PATCH the singleton babies row (#6 settings UI).

The babies table already has `dob` from #37; this PR exposes it for
the first time via `update_baby` + the Settings → Baby tab.
"""

from __future__ import annotations

from nbio.models import BabyUpdate
from nbio.repo import baby, update_baby


def test_update_baby_name_only(conn):
    out = update_baby(conn, BabyUpdate(name="Mai"))
    assert out["name"] == "Mai"
    assert out["dob"] is None  # unchanged


def test_update_baby_dob_only(conn):
    out = update_baby(conn, BabyUpdate(dob="2026-04-20"))
    assert out["dob"] == "2026-04-20"
    assert out["name"] == "Test Baby"  # unchanged (conftest seeds this)


def test_update_baby_both_fields(conn):
    out = update_baby(conn, BabyUpdate(name="Mai", dob="2026-04-20"))
    assert out["name"] == "Mai"
    assert out["dob"] == "2026-04-20"


def test_update_baby_partial_preserves_unsupplied_field(conn):
    """Setting only `dob` must not blank out `name`."""
    update_baby(conn, BabyUpdate(name="Mai"))
    update_baby(conn, BabyUpdate(dob="2026-04-20"))
    row = baby(conn)
    assert row["name"] == "Mai"
    assert row["dob"] == "2026-04-20"


def test_baby_read_returns_dob_after_update(conn):
    """The existing `repo.baby()` exposes the new dob value."""
    update_baby(conn, BabyUpdate(dob="2026-04-20"))
    assert baby(conn)["dob"] == "2026-04-20"


def test_update_baby_empty_patch_returns_current_row(conn):
    """Empty PATCH is a no-op + returns the current row."""
    out = update_baby(conn, BabyUpdate())
    assert out["name"] == "Test Baby"
    assert out["dob"] is None


def test_update_baby_rolls_back_on_sql_error(conn):
    """A mid-update failure rolls back the transaction; the row stays intact."""
    import pytest

    from tests.conftest import FailingConn

    proxy = FailingConn(conn, "UPDATE babies")
    with pytest.raises(Exception, match="forced failure"):
        update_baby(proxy, BabyUpdate(name="Mai"))
    # Original name preserved.
    assert baby(conn)["name"] == "Test Baby"
