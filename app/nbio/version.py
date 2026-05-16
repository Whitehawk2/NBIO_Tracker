"""
Single source of truth for the cache-busting version that drives the
service-worker cache name (issue #23).

We hash the contents of `nbio/static/` rather than reading a release
tag or pyproject version, so the cache name changes whenever the
shell actually changes — no release-bumping discipline required. The
hash is short (12 hex chars) because it's just a discriminator, not
a content-integrity check.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"


def static_assets_hash() -> str:
    """Stable 12-char hex hash of every file under STATIC_DIR.

    Path-and-content sensitive (renames count as changes); insertion-
    order independent (sorted before hashing).
    """
    h = hashlib.sha256()
    for f in sorted(STATIC_DIR.rglob("*")):
        if not f.is_file():
            continue
        h.update(f.relative_to(STATIC_DIR).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:12]
