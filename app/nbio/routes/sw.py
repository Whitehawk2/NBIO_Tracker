"""
Versioned service worker + /api/version endpoint (issue #23).

The static service-worker source contains the placeholder
`__NBIO_VERSION__` for the cache name. We serve it through a route
that does the substitution at response time and disables HTTP
caching, so an updated SW reaches clients on the next request.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from ..version import static_assets_hash

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SW_SOURCE = STATIC_DIR / "sw.js"

router = APIRouter()


@router.get("/static/sw.js")
def serve_versioned_sw() -> Response:
    """
    Substitutes `__NBIO_VERSION__` in the SW source with the current
    static-assets hash, then serves it with Cache-Control: no-cache so
    browsers revalidate every time (the default 24h SW revalidation
    cap would otherwise delay updates).
    """
    body = SW_SOURCE.read_text().replace("__NBIO_VERSION__", static_assets_hash())
    return Response(
        content=body,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/api/version")
def get_version() -> dict[str, str]:
    return {"version": static_assets_hash()}
