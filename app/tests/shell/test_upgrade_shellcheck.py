"""shellcheck + bash -n on upgrade.sh — same gate the other scripts pass."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "upgrade.sh"


def test_upgrade_script_exists():
    assert SCRIPT.exists(), f"missing: {SCRIPT}"


@pytest.mark.skipif(
    shutil.which("shellcheck") is None, reason="shellcheck not installed"
)
def test_shellcheck_warning_clean():
    result = subprocess.run(
        ["shellcheck", "--severity=warning", str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"shellcheck failed on {SCRIPT}:\n{result.stdout}\n{result.stderr}"
    )


def test_bash_syntax_check():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
