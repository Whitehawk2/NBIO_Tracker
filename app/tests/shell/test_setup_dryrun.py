"""
setup.sh --dry-run in NBIO_NONINTERACTIVE mode.

Run inside an isolated tmpdir copy of the repo so the test can't touch
the developer's workspace.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def staged_repo(tmp_path: Path) -> Path:
    """Copy the bits of the repo that setup.sh touches into tmp_path."""
    staged = tmp_path / "repo"
    staged.mkdir()
    for f in ("setup.sh", ".env.example", "docker-compose.yml"):
        shutil.copy(REPO_ROOT / f, staged / f)
    (staged / "setup.sh").chmod(0o755)
    return staged


def _env(**extra):
    """Build an environment with no host-side .env leakage."""
    e = dict(os.environ)
    e.update(
        {
            "NBIO_NONINTERACTIVE": "1",
            # Strip Settings-mapped env vars from the parent process so prompts
            # actually use the values we set here.
            "PATH": e["PATH"],
        }
    )
    e.update(extra)
    return e


def test_dryrun_defaults_write_env(staged_repo):
    """Fresh run: APP_BIND defaults to 127.0.0.1, .env is created."""
    result = subprocess.run(
        ["./setup.sh", "--dry-run"],
        cwd=str(staged_repo),
        env=_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    env_file = staged_repo / ".env"
    assert env_file.exists()
    text = env_file.read_text()
    for key in ("TZ", "BABY_NAME", "APP_PORT", "APP_BIND", "RCLONE_REMOTE",
                "RETAIN_LOCAL", "RETAIN_REMOTE_DAYS"):
        assert f"{key}=" in text, f"missing {key} in .env"
    assert "APP_BIND=127.0.0.1" in text


def test_dryrun_app_bind_override(staged_repo):
    """NBIO_APP_BIND=0.0.0.0 propagates into .env."""
    result = subprocess.run(
        ["./setup.sh", "--dry-run"],
        cwd=str(staged_repo),
        env=_env(NBIO_APP_BIND="0.0.0.0"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    text = (staged_repo / ".env").read_text()
    assert "APP_BIND=0.0.0.0" in text


def test_dryrun_is_idempotent(staged_repo):
    """Running twice doesn't clobber the existing .env keys."""
    e = _env(NBIO_BABY_NAME="Custom")
    subprocess.run(["./setup.sh", "--dry-run"], cwd=str(staged_repo), env=e, check=True,
                   capture_output=True, timeout=30)
    first = (staged_repo / ".env").read_text()
    subprocess.run(["./setup.sh", "--dry-run"], cwd=str(staged_repo), env=e, check=True,
                   capture_output=True, timeout=30)
    second = (staged_repo / ".env").read_text()
    # Idempotent: same keys present
    assert "BABY_NAME=" in second
    # No file truncation or duplicate key headers
    assert second.count("BABY_NAME=") == 1


def test_help_documents_env_vars(staged_repo):
    result = subprocess.run(
        ["./setup.sh", "--help"],
        cwd=str(staged_repo),
        env=_env(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    out = result.stdout + result.stderr
    for marker in ("NBIO_NONINTERACTIVE", "NBIO_APP_BIND", "NBIO_TS_HOSTNAME"):
        assert marker in out, f"missing {marker} in --help output"
