"""
Source-level pins for the setup.sh Tailscale transparency contract
(closes #12 script side).

When the Tailscale block fails (MagicDNS off, certs disabled, sudo
prompt times out, etc.) the user has no idea what command ran or how
to recover. These tests pin the contract:

1. The exact `tailscale serve …` command is echoed BEFORE invoking it,
   prefixed with `→`, so the user sees what we're about to run.
2. On failure, three recovery commands are printed (`status` / `re-try`
   / `reset`) plus a `reason:` line capturing the tailscale daemon's
   first stderr line.
3. A `--verbose` flag (or `NBIO_VERBOSE=1`) is honoured to expose the
   full block via `set -x`.

Why source-level: setup.sh's tailscale block needs a real tailscale
daemon to exercise end-to-end; we already have shellcheck + a dry-run
test that doesn't hit tailscale. These pins guarantee the contract
strings exist regardless of CI infrastructure.
"""

from __future__ import annotations

from pathlib import Path

SETUP_SH = Path(__file__).resolve().parents[3] / "setup.sh"


def _src() -> str:
    return SETUP_SH.read_text()


def test_setup_echoes_tailscale_command_before_running():
    """
    The `tailscale serve` call must be preceded by an echo showing the
    exact command (no sudo prefix). Otherwise a failure is opaque —
    the user doesn't even know what was attempted.
    """
    src = _src()
    # Find the tailscale serve block
    idx = src.find("tailscale serve --bg --https=443")
    assert idx >= 0, "couldn't find tailscale serve in setup.sh"
    # Within the surrounding ~600 chars there should be a `→ ` arrow line
    # that echoes the command before invoking it.
    block = src[max(0, idx - 400) : idx + 400]
    assert "→" in block, (
        "setup.sh should echo the tailscale serve command with a `→ ` arrow "
        "BEFORE running it so failures aren't opaque"
    )


def test_setup_supports_verbose_flag():
    """
    --verbose / NBIO_VERBOSE=1 must be honoured. Helps debug Tailscale
    + rclone failures by exposing the full command stream.
    """
    src = _src()
    assert "NBIO_VERBOSE" in src, (
        "setup.sh should support NBIO_VERBOSE=1 / --verbose for tracing"
    )
    assert "--verbose" in src, "setup.sh should accept --verbose flag"


def test_setup_prints_tailscale_recovery_hints_on_failure():
    """
    On a `tailscale serve` failure, the user gets three actionable
    recovery commands inline — not a stack trace, not "go read the
    Tailscale docs". This is the heart of the issue #12 fix.
    """
    src = _src()
    idx = src.find("tailscale serve registration failed")
    assert idx >= 0, "expected the failure warn message to remain"
    block = src[idx : idx + 1200]
    # Three recovery hints: inspect / re-try / reset.
    assert "Inspect:" in block, "missing `Inspect:` recovery hint"
    assert "Re-try:" in block, "missing `Re-try:` recovery hint"
    assert "Clear all:" in block or "reset" in block, (
        "missing `Clear all:` / `reset` recovery hint"
    )


def test_setup_captures_tailscale_stderr_reason():
    """
    When tailscale's CLI prints a stderr line, surface its first line
    so the user sees the actual error (e.g. `HTTPS certs not enabled`).
    """
    src = _src()
    # Look for either a TS_ERR/TS_REASON variable or some `2>&1` capture
    # of the tailscale call's output.
    has_reason_var = "TS_ERR" in src or "TS_REASON" in src or "ts_err" in src
    has_reason_label = "reason:" in src.lower()
    assert has_reason_var, (
        "setup.sh should capture tailscale's stderr into a variable so the "
        "first line can be printed on failure"
    )
    assert has_reason_label, (
        "setup.sh should print a `reason: <first stderr line>` on tailscale failure"
    )
