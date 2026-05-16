"""
upgrade.sh records the previous SHA to data/.upgrade-prev-ref before
checking out the target — so --rollback can find its way back.

We stub docker out via PATH so the script gets past pre-flight + backup
+ build without needing a real daemon, and stops cleanly. Both the
data/ skeleton and the prev-ref file should be present when we check.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "upgrade.sh"


def _make_docker_stub(stub_dir: Path) -> None:
    """A docker shim that always exits 0 for the calls upgrade.sh makes."""
    stub_dir.mkdir(parents=True, exist_ok=True)
    stub = stub_dir / "docker"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "# Minimal docker stub for upgrade.sh tests.\n"
        'if [[ "$1 $2" == "compose version" ]]; then\n'
        '  echo "Docker Compose version v2.99.0"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$1" == "version" ]]; then\n'
        '  echo "Docker version 99.0.0"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    stub.chmod(0o755)


@pytest.fixture
def staged_repo(tmp_path: Path) -> Path:
    """A git repo with upgrade.sh, a docker-compose stub, two tags."""
    staged = tmp_path / "repo"
    staged.mkdir()
    shutil.copy(SCRIPT, staged / "upgrade.sh")
    (staged / "upgrade.sh").chmod(0o755)
    # docker-compose.yml — upgrade.sh expects it
    (staged / "docker-compose.yml").write_text("services: {}\n")
    (staged / ".gitignore").write_text("data/\n")

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=str(staged), check=True, capture_output=True, text=True
        )

    git("init", "-q", "-b", "master")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("config", "commit.gpgsign", "false")
    git("config", "tag.gpgsign", "false")
    git("add", ".")
    git("commit", "-q", "-m", "v0.9.0 commit")
    git("tag", "-a", "v0.9.0", "-m", "v0.9.0")
    # Second commit so v1.0.0 is a different SHA
    (staged / "marker.txt").write_text("v1.0.0")
    git("add", ".")
    git("commit", "-q", "-m", "v1.0.0 commit")
    git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
    # Self-remote so `git fetch origin` succeeds with no real network
    git("remote", "add", "origin", str(staged))
    return staged


@pytest.fixture
def env_with_stub(tmp_path):
    stub_dir = tmp_path / "stubs"
    _make_docker_stub(stub_dir)
    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    env["NBIO_NONINTERACTIVE"] = "1"
    env["NBIO_SKIP_BACKUP"] = "1"   # contract: skip the docker compose exec backup
    env["NBIO_SKIP_BUILD"] = "1"    # contract: skip docker compose build + up
    env["NBIO_SKIP_HEALTHZ"] = "1"  # contract: skip the healthz poll
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


def test_upgrade_writes_prev_ref(staged_repo, env_with_stub):
    """After upgrading from v0.9.0 → v1.0.0, prev-ref records v0.9.0's SHA."""
    # Start at v0.9.0
    subprocess.run(
        ["git", "checkout", "-q", "v0.9.0"],
        cwd=str(staged_repo),
        check=True,
    )
    prev_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(staged_repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    r = _run(staged_repo, "v1.0.0", "--yes", env=env_with_stub)
    assert r.returncode == 0, r.stdout + r.stderr

    prev_ref_file = staged_repo / "data" / ".upgrade-prev-ref"
    assert prev_ref_file.exists(), "upgrade.sh should have written data/.upgrade-prev-ref"
    assert prev_ref_file.read_text().strip() == prev_sha

    # And HEAD has actually moved to v1.0.0
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(staged_repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    v1_sha = subprocess.run(
        ["git", "rev-parse", "v1.0.0^{commit}"],
        cwd=str(staged_repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_sha == v1_sha


def test_upgrade_refuses_with_dirty_tree(staged_repo, env_with_stub):
    """Uncommitted changes should block the upgrade — safety, not stash."""
    subprocess.run(["git", "checkout", "-q", "v0.9.0"], cwd=str(staged_repo), check=True)
    (staged_repo / "marker.txt").write_text("dirty")
    r = _run(staged_repo, "v1.0.0", "--yes", env=env_with_stub)
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "uncommitted" in out.lower() or "dirty" in out.lower()
