"""shellcheck every *.sh in the repo at warning severity or higher."""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SHELL_FILES = [
    REPO_ROOT / "setup.sh",
    REPO_ROOT / "remove.sh",
    REPO_ROOT / "backup" / "backup.sh",
    REPO_ROOT / "backup" / "restore.sh",
]


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
@pytest.mark.parametrize("path", SHELL_FILES, ids=lambda p: p.name)
def test_shellcheck_warning_clean(path):
    assert path.exists(), f"missing: {path}"
    result = subprocess.run(
        ["shellcheck", "--severity=warning", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"shellcheck failed on {path}:\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.parametrize("path", SHELL_FILES, ids=lambda p: p.name)
def test_bash_syntax_check(path):
    """`bash -n` validates syntax without executing."""
    assert path.exists()
    result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"
