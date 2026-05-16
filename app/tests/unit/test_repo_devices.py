"""upsert_device + list_devices."""

from nbio.models import DeviceUpsert
from nbio.repo import list_devices, upsert_device


def test_insert_new_device(conn):
    d = upsert_device(conn, "dev-1", DeviceUpsert(name="Mum", color="#4F8BFF"))
    assert d["id"] == "dev-1"
    assert d["name"] == "Mum"
    assert d["color"] == "#4F8BFF"
    assert d["created_at"]
    assert d["updated_at"]


def test_update_existing_device(conn):
    upsert_device(conn, "dev-1", DeviceUpsert(name="Mum", color="#4F8BFF"))
    updated = upsert_device(conn, "dev-1", DeviceUpsert(name="Mom", color="#FF00AA"))
    assert updated["id"] == "dev-1"
    assert updated["name"] == "Mom"
    assert updated["color"] == "#FF00AA"
    # Single row, not two
    assert len(list_devices(conn)) == 1


def test_upsert_without_name(conn):
    d = upsert_device(conn, "dev-2", DeviceUpsert(color="#000000"))
    assert d["name"] is None


def test_list_devices_empty(conn):
    assert list_devices(conn) == []


def test_list_devices_ordered_by_created_at(conn):
    upsert_device(conn, "dev-a", DeviceUpsert(color="#aaaaaa"))
    upsert_device(conn, "dev-b", DeviceUpsert(color="#bbbbbb"))
    devices = list_devices(conn)
    assert [d["id"] for d in devices] == ["dev-a", "dev-b"]


def test_updated_at_changes_on_update(conn, freezer):
    """
    Bumping updated_at on every upsert is the contract. The prior version
    of this test used `... != ... or color == "#bbbbbb"` — the or-clause
    is unconditionally true given the test setup, so the timestamp half
    never had to hold (issue #21 worth-fixing). Freezer pins two distinct
    moments so the timestamps MUST differ.
    """
    freezer.move_to("2026-05-16T03:00:00Z")
    first = upsert_device(conn, "dev-1", DeviceUpsert(color="#aaaaaa"))
    freezer.move_to("2026-05-16T03:30:00Z")
    second = upsert_device(conn, "dev-1", DeviceUpsert(color="#bbbbbb"))
    assert second["updated_at"] != first["updated_at"]
    assert second["color"] == "#bbbbbb"
    # Invariant: updated_at always moves forward
    assert second["updated_at"] > first["updated_at"]
