"""
README docs contract for the v1.1.0 networking pass (closes #13).

These tests don't validate prose — they pin a few structural anchors
so the networking docs can't silently regress:

1. A "Choosing how to expose the app" / Networking section with three
   named patterns: Local-only, LAN-only, Tailscale.
2. The LAN-only pattern carries an explicit no-auth warning.
3. A "Tailscale troubleshooting" subsection with the common-errors
   table (#12 README side).
4. A short decision tree in Quick start.
5. The `APP_PORT` knob is described as controlling BOTH the Docker
   host port AND the Tailscale backend — surfacing the
   "port 9090" use case the user asked about.

Why source-level: end-to-end testing the README would mean firing up
a real Tailscale tailnet. These pins guarantee the contracts exist
regardless of CI infrastructure.
"""

from __future__ import annotations

from pathlib import Path

README = Path(__file__).resolve().parents[3] / "README.md"


def _src() -> str:
    return README.read_text()


def test_readme_has_three_named_networking_patterns():
    """
    Replace the Tailscale-heavy view with three equally-weighted
    deployment options so the LAN-only / local-only paths aren't
    second-class.
    """
    src = _src()
    # Each pattern is anchored by a distinctive header label.
    assert "Local-only" in src, (
        "README must name a `Local-only` networking pattern explicitly"
    )
    assert "LAN-only" in src, (
        "README must name a `LAN-only` networking pattern explicitly"
    )
    assert "Tailscale" in src, "README must keep the Tailscale pattern"


def test_lan_only_carries_no_auth_warning():
    """
    NBIO has no auth. Setting APP_BIND=0.0.0.0 exposes it to every
    device on the LAN. The README must call this out, not just bury it.
    """
    src = _src()
    # Look for "no auth" or "no-auth" near "LAN" wording.
    idx = src.find("LAN-only")
    assert idx >= 0
    block = src[idx : idx + 1500]
    has_warning = (
        "no auth" in block.lower()
        or "no-auth" in block.lower()
        or "anyone on" in block.lower()
    )
    assert has_warning, (
        "LAN-only section must carry an explicit no-auth warning "
        "(anyone on the LAN can read/write events)"
    )


def test_tailscale_troubleshooting_subsection_present():
    """
    The user's #12 ask: when `tailscale serve` fails, the README must
    surface the recovery commands + common-errors table.
    """
    src = _src()
    assert "Tailscale troubleshooting" in src, (
        "README must have a `Tailscale troubleshooting` subsection"
    )
    # The common-errors table mentions at least the two most-asked-about
    # admin-panel toggles.
    idx = src.find("Tailscale troubleshooting")
    block = src[idx : idx + 3000]
    assert "MagicDNS" in block, "troubleshooting must mention MagicDNS"
    assert "HTTPS" in block or "certs" in block.lower(), (
        "troubleshooting must mention HTTPS Certificates toggle"
    )
    # The three actionable commands.
    assert "tailscale serve status" in block, "missing `tailscale serve status`"
    assert "tailscale serve reset" in block, "missing `tailscale serve reset`"


def test_quickstart_has_pattern_decision_tree():
    """
    A two/three-line decision tree near Quick start so a fresh reader
    picks the right pattern in seconds.
    """
    src = _src()
    idx = src.find("## Quick start")
    assert idx >= 0
    block = src[idx : idx + 2500]
    # Anchor on the three pattern keywords appearing in the decision tree
    # (the brief 3-line version, not the full sections below).
    assert "trying it out locally" in block.lower() or "localhost" in block.lower(), (
        "decision tree should point at the local-only path"
    )
    assert "wi-fi" in block.lower() or "lan" in block.lower() or "apk_bind" in block.lower(), (
        "decision tree should point at the LAN-only path"
    )


def test_app_port_documents_dual_role():
    """
    The user asked for a way to change the Tailscale-side port (e.g.
    9090:8000). APP_PORT already controls BOTH Docker host port AND
    the Tailscale backend; surface this in the README so it's discoverable.
    """
    src = _src()
    # Find an APP_PORT mention near 'Tailscale' or 'both' — pin the
    # explanation that they share the same env var.
    has_explicit_link = False
    for marker in ("APP_PORT", "9090"):
        idx = src.find(marker)
        if idx < 0:
            continue
        window = src[idx : idx + 800]
        if "Tailscale" in window and ("9090" in window or "both" in window.lower()):
            has_explicit_link = True
            break
    assert has_explicit_link, (
        "README must explain that APP_PORT changes BOTH the Docker host "
        "port AND the Tailscale backend (e.g. APP_PORT=9090 gives "
        "9090:8000 + Tailscale serving from :9090). This is the "
        "discoverability fix for v1.1.0."
    )
