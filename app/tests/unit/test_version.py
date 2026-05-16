"""
`nbio.version.static_assets_hash()` is the single source of truth driving
the service-worker cache name. Tested in isolation here; the HTTP layer
that surfaces it is tested in tests/api/test_version_endpoint.py and
tests/api/test_sw_versioning.py.

This fixes #23: a static-asset-content-derived hash means the cache name
changes whenever the shell changes — no release-bumping discipline
required.
"""

import re

from nbio.version import static_assets_hash


def test_hash_is_stable_across_calls():
    """Deterministic — calling twice returns the same value."""
    assert static_assets_hash() == static_assets_hash()


def test_hash_is_a_short_hex_string():
    """12 hex chars — plenty of entropy for a cache-name discriminator."""
    h = static_assets_hash()
    assert re.fullmatch(r"[0-9a-f]{12}", h), f"unexpected hash format: {h!r}"


def test_hash_changes_when_a_static_file_changes(tmp_path, monkeypatch):
    """
    Hashing a different static tree produces a different value. This is
    the property the SW-cache contract depends on: change app.js → new
    hash → new SW cache name → activate purges old cache → fresh shell.
    """
    from nbio import version

    a = tmp_path / "site-a"
    a.mkdir()
    (a / "app.js").write_text("console.log('v1');\n")
    monkeypatch.setattr(version, "STATIC_DIR", a)
    h_a = static_assets_hash()

    b = tmp_path / "site-b"
    b.mkdir()
    (b / "app.js").write_text("console.log('v2');\n")
    monkeypatch.setattr(version, "STATIC_DIR", b)
    h_b = static_assets_hash()

    assert h_a != h_b, "changing a file's contents must change the hash"


def test_hash_depends_on_filenames_too(tmp_path, monkeypatch):
    """A rename is a behaviour-affecting change (referenced URLs change)."""
    from nbio import version

    a = tmp_path / "site-a"
    a.mkdir()
    (a / "app.js").write_text("X")
    monkeypatch.setattr(version, "STATIC_DIR", a)
    h_a = static_assets_hash()

    b = tmp_path / "site-b"
    b.mkdir()
    (b / "renamed.js").write_text("X")
    monkeypatch.setattr(version, "STATIC_DIR", b)
    h_b = static_assets_hash()

    assert h_a != h_b, "renaming a file must change the hash"


def test_hash_is_order_independent(tmp_path, monkeypatch):
    """
    Insertion order of files into the directory shouldn't affect the
    hash — the function sorts before hashing.
    """
    from nbio import version

    a = tmp_path / "site-a"
    a.mkdir()
    (a / "b.txt").write_text("b")
    (a / "a.txt").write_text("a")
    monkeypatch.setattr(version, "STATIC_DIR", a)
    h_a = static_assets_hash()

    b = tmp_path / "site-b"
    b.mkdir()
    (b / "a.txt").write_text("a")
    (b / "b.txt").write_text("b")
    monkeypatch.setattr(version, "STATIC_DIR", b)
    h_b = static_assets_hash()

    assert h_a == h_b


def test_hash_for_the_real_static_dir_is_a_hex_string():
    """End-to-end: the real nbio/static/ produces a valid 12-char hex."""
    h = static_assets_hash()
    assert len(h) == 12
    int(h, 16)  # parses as hex
