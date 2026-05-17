"""
upgrade.sh must NEVER exit non-zero silently — every failure path produces a
visible diagnostic on stderr (issue #28 finding #3).

Two failure modes the user reported in production:
- `./upgrade.sh --ref master` exited 1 with no visible error message.

This test file exercises specific silent-fail-prone steps in the script,
asserting both:
1. The script exits non-zero (correct error propagation).
2. stderr contains either a `die` message OR the ERR trap's
   `upgrade.sh aborted at line N running: CMD` diagnostic.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "upgrade.sh"


def _make_docker_stub(stub_dir: Path, fail_on: str | None = None) -> None:
    """
    A docker shim. If `fail_on` is set, the matching sub-command exits 1
    with a stderr message — to simulate a real `docker` failure mode.

    `fail_on` values:
      - "build"        → fail on `docker compose build` / `... --pull`
      - "up"           → fail on `docker compose up -d`
      - "backup-exec"  → fail on `docker compose exec -T backup ...`
    """
    stub_dir.mkdir(parents=True, exist_ok=True)
    fail_cmd = fail_on or ""
    stub = stub_dir / "docker"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        '# Stub docker for upgrade.sh tests. Optional failure injection.\n'
        f'FAIL_ON="{fail_cmd}"\n'
        'if [[ "$1 $2" == "compose version" ]]; then\n'
        '  echo "Docker Compose version v2.99.0"; exit 0\n'
        "fi\n"
        'if [[ "$1" == "version" ]]; then\n'
        '  echo "Docker version 99.0.0"; exit 0\n'
        "fi\n"
        'if [[ "$1 $2" == "compose build" && "$FAIL_ON" == "build" ]]; then\n'
        '  echo "stub: simulated docker build failure" >&2; exit 1\n'
        "fi\n"
        'if [[ "$1 $2 $3" == "compose up -d" && "$FAIL_ON" == "up" ]]; then\n'
        '  echo "stub: simulated docker up failure" >&2; exit 1\n'
        "fi\n"
        'if [[ "$1 $2 $3" == "compose exec -T" && "$FAIL_ON" == "backup-exec" ]]; then\n'
        '  echo "stub: backup container is not running" >&2; exit 1\n'
        "fi\n"
        "exit 0\n"
    )
    stub.chmod(0o755)


@pytest.fixture
def staged_repo(tmp_path: Path) -> Path:
    """A git repo with upgrade.sh, a docker-compose stub, two tags, master tracking origin."""
    staged = tmp_path / "repo"
    staged.mkdir()
    shutil.copy(SCRIPT, staged / "upgrade.sh")
    (staged / "upgrade.sh").chmod(0o755)
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
    (staged / "marker.txt").write_text("v1.0.0")
    git("add", ".")
    git("commit", "-q", "-m", "v1.0.0 commit")
    git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
    git("remote", "add", "origin", str(staged))
    git("fetch", "--quiet", "origin")
    return staged


def _run(script_dir, *args, env, timeout=20):
    return subprocess.run(
        ["./upgrade.sh", *args],
        cwd=str(script_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _base_env(stub_dir):
    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    env["NBIO_NONINTERACTIVE"] = "1"
    return env


# ---------------------------------------------------------------------------
# ERR trap: every uncaught failure must produce a diagnostic.
# ---------------------------------------------------------------------------


def test_err_trap_fires_on_docker_build_failure(staged_repo, tmp_path):
    """
    Bare `docker compose build` on line 284 had no `|| die`. If docker fails,
    the script exited 1 silently. The ERR trap now produces a diagnostic.
    """
    stub_dir = tmp_path / "stubs"
    _make_docker_stub(stub_dir, fail_on="build")
    env = _base_env(stub_dir)
    env["NBIO_SKIP_BACKUP"] = "1"
    env["NBIO_SKIP_HEALTHZ"] = "1"
    # Do NOT skip build — this is the step we want to fail

    subprocess.run(["git", "checkout", "-q", "v0.9.0"], cwd=str(staged_repo), check=True)
    r = _run(staged_repo, "v1.0.0", "--yes", env=env)

    assert r.returncode != 0
    combined = r.stdout + r.stderr
    # Either the trap fired or a `die` message — but stderr MUST not be empty
    assert combined.strip(), "upgrade.sh exited non-zero with no visible diagnostic"
    # Trap signature OR a clear failure description
    has_trap = "aborted at line" in combined
    has_diagnostic = "docker compose build" in combined or "build failed" in combined.lower()
    assert has_trap or has_diagnostic, (
        f"no diagnostic surfaced. Combined output:\n{combined}"
    )


def test_err_trap_fires_on_docker_up_failure(staged_repo, tmp_path):
    """Same shape, but failing on `docker compose up -d`."""
    stub_dir = tmp_path / "stubs"
    _make_docker_stub(stub_dir, fail_on="up")
    env = _base_env(stub_dir)
    env["NBIO_SKIP_BACKUP"] = "1"
    env["NBIO_SKIP_HEALTHZ"] = "1"

    subprocess.run(["git", "checkout", "-q", "v0.9.0"], cwd=str(staged_repo), check=True)
    r = _run(staged_repo, "v1.0.0", "--yes", env=env)

    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert combined.strip(), "silent exit on `docker compose up -d` failure"
    assert "aborted at line" in combined or "up" in combined.lower()


def test_err_trap_diagnostic_includes_line_number(staged_repo, tmp_path):
    """
    The trap's value-add is identifying WHERE failure happened. Diagnostic
    must include 'line N' for some integer N so the operator can grep the
    script.
    """
    import re

    stub_dir = tmp_path / "stubs"
    _make_docker_stub(stub_dir, fail_on="build")
    env = _base_env(stub_dir)
    env["NBIO_SKIP_BACKUP"] = "1"
    env["NBIO_SKIP_HEALTHZ"] = "1"

    subprocess.run(["git", "checkout", "-q", "v0.9.0"], cwd=str(staged_repo), check=True)
    r = _run(staged_repo, "v1.0.0", "--yes", env=env)

    combined = r.stdout + r.stderr
    assert re.search(r"line\s+\d+", combined), (
        f"trap should include 'line N' in its diagnostic; got:\n{combined}"
    )


# ---------------------------------------------------------------------------
# --ref master positive path: must work when local master is present (post-
# initial-checkout). Regression test so the upcoming `|| die` changes don't
# break the happy path.
# ---------------------------------------------------------------------------


def test_ref_master_succeeds_when_local_master_exists(staged_repo, tmp_path):
    """The user's reported failure path: `./upgrade.sh --ref master`.
    With local master present, it should succeed cleanly."""
    stub_dir = tmp_path / "stubs"
    _make_docker_stub(stub_dir)
    env = _base_env(stub_dir)
    env["NBIO_SKIP_BACKUP"] = "1"
    env["NBIO_SKIP_BUILD"] = "1"
    env["NBIO_SKIP_HEALTHZ"] = "1"

    # Start at v0.9.0 (detached) — common state after a prior tag-based upgrade
    subprocess.run(["git", "checkout", "-q", "v0.9.0"], cwd=str(staged_repo), check=True)

    r = _run(staged_repo, "--ref", "master", "--yes", env=env)
    assert r.returncode == 0, r.stdout + r.stderr

    # HEAD now on local master
    head_ref = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(staged_repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_ref == "master"


# ---------------------------------------------------------------------------
# Source-level audit: no bare `git checkout` should reach the surface without
# `|| die "..."`. The trap is a safety net; explicit `|| die` is the
# preferred failure message for known-tricky steps.
# ---------------------------------------------------------------------------


def test_source_no_bare_git_checkout_quiet():
    """
    `git checkout -q "$ref"` was the most likely silent-fail spot. Every
    checkout in upgrade.sh now has either an explicit `|| die` or is
    documented as covered by the trap.
    """
    src = SCRIPT.read_text()
    lines = src.splitlines()
    offenders = []
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if "git checkout" not in stripped:
            continue
        if stripped.startswith("#"):
            continue
        # Acceptable: ends with `|| die ...` on same line OR continuation
        if "|| die" in stripped:
            continue
        # Acceptable: multi-line — check next line for `|| die`
        if i < len(lines) and "|| die" in lines[i].strip():
            continue
        offenders.append(f"line {i}: {stripped}")
    assert not offenders, (
        "Every `git checkout` in upgrade.sh must have `|| die`:\n  "
        + "\n  ".join(offenders)
    )


def test_source_declares_err_trap():
    """The ERR trap is the safety net; its presence is the contract."""
    src = SCRIPT.read_text()
    assert "trap " in src and "ERR" in src, (
        "upgrade.sh should declare a `trap ... ERR` so silent exits are impossible"
    )


def test_source_tag_fetch_uses_force():
    """
    `git fetch --tags` without --force fails when a local tag's SHA disagrees
    with origin's — common after retags or when someone fetched mid-rebase.
    The Pi hit this in production. --force makes origin's tag state win,
    which is the correct semantic for an upgrade flow.
    """
    src = SCRIPT.read_text()
    # Look for the specific tag-fetch line; must include --force
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "git fetch" in stripped and "--tags" in stripped:
            assert "--force" in stripped, (
                "`git fetch --tags` must use --force so locally-conflicting "
                f"tags don't abort the upgrade. Offending line: {stripped!r}"
            )
