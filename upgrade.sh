#!/usr/bin/env bash
# NBIO Tracker — in-place upgrade.
#
# Nix users: this script is not for you. See the flake (issue #7) for
# `nix profile upgrade`. The Docker and Nix paths are mutually exclusive.
#
# What this does:
#   1. Pre-flight: docker + docker compose v2 + git on PATH, clean tree
#   2. Resolve the target ref (default = latest annotated tag; or pass
#      a tag name; or --ref master to track the branch)
#   3. Fetch origin + tags; show the changelog and .env.example diff
#   4. Confirm (unless --yes / NBIO_NONINTERACTIVE=1)
#   5. Trigger a backup snapshot via the sidecar (refuses to upgrade if
#      this fails — set NBIO_SKIP_BACKUP=1 to override in dev)
#   6. Record current HEAD in data/.upgrade-prev-ref (for --rollback)
#   7. git checkout the target ref (fast-forward only for branches)
#   8. docker compose build (add --pull for fresh base images)
#   9. docker compose up -d
#  10. Poll /healthz up to 60s; on failure, print the rollback command
#      and exit non-zero (no auto-rollback — diagnose with logs first)
#
# Env overrides (for CI / non-interactive runs):
#   NBIO_NONINTERACTIVE=1   skip the confirmation prompt
#   NBIO_SKIP_BACKUP=1      skip the docker compose exec backup step
#   NBIO_SKIP_BUILD=1       skip docker compose build + up (dev / tests)
#   NBIO_SKIP_HEALTHZ=1     skip the /healthz poll (dev / tests)
#   NBIO_APP_PORT           port used for healthz (default: 8000)
#
# Flags:
#   --ref <branch|tag>   pick a specific ref (default: latest annotated tag)
#   --rollback           revert to data/.upgrade-prev-ref's recorded SHA
#   --yes                non-interactive confirm
#   --pull               docker compose build --pull (refresh base images)
#   --resolve-only       dry-run: print the resolved target ref, exit
#   --help               this help

set -euo pipefail

# ----- args ------------------------------------------------------------------
REF=""
ROLLBACK=0
YES=0
PULL=0
RESOLVE_ONLY=0
EXPLICIT_TAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)           REF="${2:-}"; shift 2 ;;
    --rollback)      ROLLBACK=1; shift ;;
    --yes|-y)        YES=1; shift ;;
    --pull)          PULL=1; shift ;;
    --resolve-only)  RESOLVE_ONLY=1; shift ;;
    --help|-h)
      sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *)
      if [[ -n "$EXPLICIT_TAG" ]]; then
        echo "extra positional argument: $1 (already have '$EXPLICIT_TAG')" >&2
        exit 2
      fi
      EXPLICIT_TAG="$1"; shift ;;
  esac
done

[[ "${NBIO_NONINTERACTIVE:-0}" == "1" ]] && YES=1

# ----- helpers ---------------------------------------------------------------
info()  { printf '\033[1;34m::\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
err()   { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }

die()   { err "$1"; exit "${2:-1}"; }

# ----- pre-flight ------------------------------------------------------------
preflight() {
  command -v git >/dev/null 2>&1 \
    || die "git not found. The upgrade flow needs a git checkout."
  command -v docker >/dev/null 2>&1 \
    || die "docker not found. Install: https://docs.docker.com/engine/install/"
  docker compose version >/dev/null 2>&1 \
    || die "docker compose v2 not found. Install the compose plugin."

  # Working tree must be clean — don't silently stash someone's edits.
  if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    die "working tree has uncommitted changes. Commit or stash them first."
  fi
}

# ----- ref resolution --------------------------------------------------------
# Sets TARGET_REF and TARGET_KIND ("tag" | "branch" | "sha"). Exits non-zero
# on unresolvable input.
resolve_target() {
  # Explicit tag positional wins
  if [[ -n "$EXPLICIT_TAG" ]]; then
    if git rev-parse --verify --quiet "refs/tags/$EXPLICIT_TAG" >/dev/null; then
      TARGET_REF="$EXPLICIT_TAG"
      TARGET_KIND="tag"
      return 0
    fi
    die "tag not found: $EXPLICIT_TAG"
  fi

  # --ref branch (or tag)
  if [[ -n "$REF" ]]; then
    if git rev-parse --verify --quiet "refs/heads/$REF" >/dev/null \
        || git rev-parse --verify --quiet "refs/remotes/origin/$REF" >/dev/null; then
      TARGET_REF="$REF"
      TARGET_KIND="branch"
      return 0
    fi
    if git rev-parse --verify --quiet "refs/tags/$REF" >/dev/null; then
      TARGET_REF="$REF"
      TARGET_KIND="tag"
      return 0
    fi
    die "ref not found: $REF"
  fi

  # Default: latest annotated tag
  local latest
  latest=$(git describe --tags --abbrev=0 2>/dev/null || true)
  if [[ -z "$latest" ]]; then
    die "no annotated tags in this repo. Pass --ref master or a specific tag."
  fi
  TARGET_REF="$latest"
  TARGET_KIND="tag"
}

# ----- rollback path ---------------------------------------------------------
do_rollback() {
  preflight
  local prev_ref_file="data/.upgrade-prev-ref"
  [[ -f "$prev_ref_file" ]] \
    || die "no prev-ref recorded (data/.upgrade-prev-ref missing). Nothing to roll back."
  local prev_sha
  prev_sha=$(tr -d '[:space:]' < "$prev_ref_file")
  [[ -n "$prev_sha" ]] || die "prev-ref file is empty."

  if ! git rev-parse --verify --quiet "$prev_sha^{commit}" >/dev/null; then
    die "prev-ref $prev_sha is unknown to this repo (stale or never fetched)."
  fi

  local cur_sha
  cur_sha=$(git rev-parse HEAD)
  info "Rolling back: $cur_sha → $prev_sha"

  if (( ! YES )); then
    read -r -p "  Proceed? [y/N]: " ans
    [[ "${ans,,}" =~ ^y(es)?$ ]] || die "aborted." 0
  fi

  git checkout -q "$prev_sha" || die "checkout failed."
  ok "checked out $prev_sha"

  if [[ "${NBIO_SKIP_BUILD:-0}" != "1" ]]; then
    info "Rebuilding stack"
    docker compose build
    docker compose up -d
  else
    info "NBIO_SKIP_BUILD=1 → skipping docker compose build/up"
  fi

  healthz_or_warn
  ok "rollback complete."
}

# ----- healthz wait ----------------------------------------------------------
healthz_or_warn() {
  if [[ "${NBIO_SKIP_HEALTHZ:-0}" == "1" ]]; then
    info "NBIO_SKIP_HEALTHZ=1 → skipping /healthz poll"
    return 0
  fi
  local port="${NBIO_APP_PORT:-${APP_PORT:-8000}}"
  info "Waiting for /healthz on port $port (up to 60s)"
  for _ in $(seq 1 60); do
    if curl -sf "http://localhost:${port}/healthz" >/dev/null 2>&1; then
      ok "/healthz responded"
      return 0
    fi
    sleep 1
  done
  err "/healthz did not respond within 60s."
  err "Inspect: docker compose logs app"
  err "Rollback: ./upgrade.sh --rollback"
  exit 1
}

# ----- main ------------------------------------------------------------------

if (( ROLLBACK )); then
  do_rollback
  exit 0
fi

preflight

if (( ! RESOLVE_ONLY )); then
  info "Fetching origin"
  git fetch --quiet origin
  git fetch --quiet --tags origin
fi

resolve_target

# Resolve to a concrete SHA so we can compare safely
TARGET_SHA=$(git rev-parse "$TARGET_REF^{commit}")
CURRENT_SHA=$(git rev-parse HEAD)

if (( RESOLVE_ONLY )); then
  info "Target ref: $TARGET_REF ($TARGET_KIND)"
  info "Target SHA: $TARGET_SHA"
  info "Current SHA: $CURRENT_SHA"
  if [[ "$TARGET_SHA" == "$CURRENT_SHA" ]]; then
    info "Already on target — no upgrade needed."
  fi
  exit 0
fi

if [[ "$TARGET_SHA" == "$CURRENT_SHA" ]]; then
  ok "Already on $TARGET_REF — nothing to do."
  exit 0
fi

info "Upgrade plan"
echo "  current: $CURRENT_SHA"
echo "  target:  $TARGET_REF ($TARGET_SHA)"
echo ""
info "Commits coming in:"
git --no-pager log --oneline "$CURRENT_SHA..$TARGET_SHA" | sed 's/^/  /' || true
echo ""

# .env.example diff — warn about new keys the user may want to mirror to .env
if git diff --quiet "$CURRENT_SHA" "$TARGET_SHA" -- .env.example; then
  : # unchanged
else
  warn ".env.example changed between current and target. Diff:"
  git --no-pager diff "$CURRENT_SHA" "$TARGET_SHA" -- .env.example | sed 's/^/  /'
  warn "Mirror any new keys you want into .env after the upgrade."
fi

if (( ! YES )); then
  read -r -p "  Proceed? [y/N]: " ans
  [[ "${ans,,}" =~ ^y(es)?$ ]] || { info "aborted."; exit 0; }
fi

# ----- backup first ----------------------------------------------------------
if [[ "${NBIO_SKIP_BACKUP:-0}" == "1" ]]; then
  info "NBIO_SKIP_BACKUP=1 → skipping pre-upgrade snapshot"
else
  info "Taking a pre-upgrade snapshot (sidecar backup.sh)"
  if ! docker compose exec -T backup /usr/local/bin/backup.sh; then
    die "backup failed. Refusing to upgrade without a snapshot. Set NBIO_SKIP_BACKUP=1 to override (dev only)."
  fi
fi

# ----- record current SHA for rollback --------------------------------------
mkdir -p data
echo "$CURRENT_SHA" > data/.upgrade-prev-ref
ok "recorded prev-ref → data/.upgrade-prev-ref"

# ----- checkout target -------------------------------------------------------
info "Checking out $TARGET_REF"
if [[ "$TARGET_KIND" == "branch" ]]; then
  git checkout -q "$TARGET_REF"
  git merge --ff-only "origin/$TARGET_REF" \
    || die "fast-forward to origin/$TARGET_REF failed."
else
  git checkout -q "$TARGET_REF"
fi
ok "HEAD is now at $(git rev-parse HEAD)"

# ----- rebuild + restart -----------------------------------------------------
if [[ "${NBIO_SKIP_BUILD:-0}" == "1" ]]; then
  info "NBIO_SKIP_BUILD=1 → skipping docker compose build/up"
else
  info "Building images"
  if (( PULL )); then
    docker compose build --pull
  else
    docker compose build
  fi
  info "Restarting stack"
  docker compose up -d
fi

healthz_or_warn

# ----- summary ---------------------------------------------------------------
echo ""
ok "Upgraded $CURRENT_SHA → $TARGET_REF"
echo ""
echo "  Rollback if anything misbehaves:  ./upgrade.sh --rollback"
echo "  Live logs:                        make logs"
echo "  Status:                           make status"
