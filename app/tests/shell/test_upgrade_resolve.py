"""
./upgrade.sh --resolve-only is a dry-run that prints which ref it would
check out, then exits without touching anything.

This is the cheapest test of the ref-resolution logic: no docker, no
backup, no checkout. Works against a tmpdir bare-of-history clone that
we seed with tags and a master HEAD.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "upgrade.sh"


def _run(script_dir: Path, *args, env_extra=None):
    """Invoke upgrade.sh in script_dir. Returns CompletedProcess."""
    import os

    env = dict(os.environ)
    env["NBIO_NONINTERACTIVE"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["./upgrade.sh", *args],
        cwd=str(script_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.fixture
def staged_repo(tmp_path: Path) -> Path:
    """A fresh git repo with upgrade.sh + a few commits + two tags."""
    staged = tmp_path / "repo"
    staged.mkdir()
    shutil.copy(SCRIPT, staged / "upgrade.sh")
    (staged / "upgrade.sh").chmod(0o755)

    # Seed a tiny git history with two annotated tags
    def git(*args, check=True):
        return subprocess.run(
            ["git", *args], cwd=str(staged), check=check, capture_output=True, text=True
        )

    (staged / ".gitignore").write_text("data/\n")

    git("init", "-q", "-b", "master")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("config", "commit.gpgsign", "false")
    git("config", "tag.gpgsign", "false")
    git("add", ".")
    git("commit", "-q", "-m", "v0.9.0 commit")
    git("tag", "-a", "v0.9.0", "-m", "v0.9.0")
    git("commit", "--allow-empty", "-q", "-m", "v1.0.0 commit")
    git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
    git("commit", "--allow-empty", "-q", "-m", "after the latest tag")
    # A self-remote so `git fetch origin` is a no-op rather than an error
    git("remote", "add", "origin", str(staged))
    return staged


def test_resolve_only_picks_latest_tag(staged_repo):
    """Default resolution = latest annotated tag (v1.0.0 here)."""
    r = _run(staged_repo, "--resolve-only")
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout + r.stderr
    assert "v1.0.0" in out
    # Should not announce the master-HEAD ref
    assert "after the latest tag" not in out


def test_resolve_only_respects_explicit_tag(staged_repo):
    """Passing a tag name resolves to that tag."""
    r = _run(staged_repo, "v0.9.0", "--resolve-only")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "v0.9.0" in r.stdout + r.stderr


def test_resolve_only_respects_ref_master(staged_repo):
    """--ref master opts into HEAD-of-branch tracking."""
    r = _run(staged_repo, "--ref", "master", "--resolve-only")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "master" in r.stdout + r.stderr


def test_resolve_only_errors_on_unknown_ref(staged_repo):
    """A non-existent tag exits non-zero with a clear message."""
    r = _run(staged_repo, "v9.9.9-nope", "--resolve-only")
    assert r.returncode != 0
    assert "v9.9.9-nope" in r.stdout + r.stderr


def test_resolve_only_errors_when_no_tags(tmp_path):
    """A repo with zero tags and no --ref bails with a hint."""
    staged = tmp_path / "blank"
    staged.mkdir()
    shutil.copy(SCRIPT, staged / "upgrade.sh")
    (staged / "upgrade.sh").chmod(0o755)
    subprocess.run(["git", "init", "-q", "-b", "master"], cwd=str(staged), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(staged), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(staged), check=True)
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"], cwd=str(staged), check=True
    )
    (staged / ".gitignore").write_text("data/\n")
    subprocess.run(["git", "add", "."], cwd=str(staged), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"],
        cwd=str(staged),
        check=True,
    )
    r = _run(staged, "--resolve-only")
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "tag" in out.lower() or "--ref" in out
