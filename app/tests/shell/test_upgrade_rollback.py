"""
./upgrade.sh --rollback reads data/.upgrade-prev-ref and checks it out.

We assemble the same kind of staged repo as test_upgrade_writes_prev_ref
but pre-populate data/.upgrade-prev-ref so the rollback path can be
exercised in isolation.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "upgrade.sh"


def _make_docker_stub(stub_dir: Path) -> None:
    stub_dir.mkdir(parents=True, exist_ok=True)
    stub = stub_dir / "docker"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1 $2" == "compose version" ]]; then\n'
        '  echo "Docker Compose version v2.99.0"; exit 0\n'
        "fi\n"
        'if [[ "$1" == "version" ]]; then\n'
        '  echo "Docker version 99.0.0"; exit 0\n'
        "fi\n"
        "exit 0\n"
    )
    stub.chmod(0o755)


@pytest.fixture
def staged_repo(tmp_path: Path) -> Path:
    staged = tmp_path / "repo"
    staged.mkdir()
    shutil.copy(SCRIPT, staged / "upgrade.sh")
    (staged / "upgrade.sh").chmod(0o755)
    (staged / "docker-compose.yml").write_text("services: {}\n")

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=str(staged), check=True, capture_output=True, text=True
        )

    git("init", "-q", "-b", "master")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("add", ".")
    git("commit", "-q", "-m", "v0.9.0 commit")
    git("tag", "-a", "v0.9.0", "-m", "v0.9.0")
    (staged / "marker.txt").write_text("v1.0.0")
    git("add", ".")
    git("commit", "-q", "-m", "v1.0.0 commit")
    git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
    return staged


@pytest.fixture
def env_with_stub(tmp_path):
    stub_dir = tmp_path / "stubs"
    _make_docker_stub(stub_dir)
    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    env["NBIO_NONINTERACTIVE"] = "1"
    env["NBIO_SKIP_BACKUP"] = "1"
    env["NBIO_SKIP_BUILD"] = "1"
    env["NBIO_SKIP_HEALTHZ"] = "1"
    return env


def _run(script_dir, *args, env):
    return subprocess.run(
        ["./upgrade.sh", *args],
        cwd=str(script_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_rollback_reads_prev_ref(staged_repo, env_with_stub):
    """Pre-populate prev-ref with v0.9.0's SHA; rollback should land us there."""
    # We're at v1.0.0 (master HEAD = v1.0.0 SHA)
    subprocess.run(
        ["git", "checkout", "-q", "v1.0.0"], cwd=str(staged_repo), check=True
    )
    v09_sha = subprocess.run(
        ["git", "rev-parse", "v0.9.0^{commit}"],
        cwd=str(staged_repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # Simulate that a previous upgrade recorded v0.9.0 as the rollback target
    (staged_repo / "data").mkdir()
    (staged_repo / "data" / ".upgrade-prev-ref").write_text(v09_sha + "\n")

    r = _run(staged_repo, "--rollback", "--yes", env=env_with_stub)
    assert r.returncode == 0, r.stdout + r.stderr

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(staged_repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == v09_sha


def test_rollback_without_prev_ref_errors(staged_repo, env_with_stub):
    """No prev-ref → can't roll back; exit non-zero with a clear message."""
    r = _run(staged_repo, "--rollback", "--yes", env=env_with_stub)
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "prev-ref" in out.lower() or "rollback" in out.lower()


def test_rollback_with_stale_prev_ref_errors(staged_repo, env_with_stub):
    """If the recorded SHA isn't reachable, rollback bails cleanly."""
    (staged_repo / "data").mkdir()
    (staged_repo / "data" / ".upgrade-prev-ref").write_text("0" * 40 + "\n")
    r = _run(staged_repo, "--rollback", "--yes", env=env_with_stub)
    assert r.returncode != 0
    assert "rev" in (r.stdout + r.stderr).lower() or "unknown" in (
        r.stdout + r.stderr
    ).lower()
