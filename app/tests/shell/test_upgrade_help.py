"""
./upgrade.sh --help documents every flag and env var the script supports.

The --help path doesn't need docker — exits before pre-flight.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "upgrade.sh"


@pytest.fixture
def script_path() -> Path:
    assert SCRIPT.exists(), f"missing: {SCRIPT}"
    return SCRIPT


def test_help_exits_zero(script_path):
    result = subprocess.run(
        [str(script_path), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "flag",
    ["--ref", "--rollback", "--yes", "--pull", "--resolve-only", "--help"],
)
def test_help_lists_every_flag(script_path, flag):
    result = subprocess.run(
        [str(script_path), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = result.stdout + result.stderr
    assert flag in out, f"--help output missing {flag}"


@pytest.mark.parametrize("env_var", ["NBIO_NONINTERACTIVE"])
def test_help_lists_env_vars(script_path, env_var):
    result = subprocess.run(
        [str(script_path), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = result.stdout + result.stderr
    assert env_var in out, f"--help output missing {env_var}"
