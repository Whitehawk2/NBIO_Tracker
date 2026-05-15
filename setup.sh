#!/usr/bin/env bash
# NBIO Tracker — one-shot setup for the Docker path.
#
# Nix users: this script is not for you.
#   See the flake (issue #7) — `nix profile install nixpkgs#nbio`
#   or the NixOS module. The Docker stack and the Nix path are mutually
#   exclusive ways to run the server; pick one and ignore the other.
#
# What this does (idempotent — safe to re-run):
#   1. Pre-flight: docker + docker compose v2 must be on PATH
#   2. Bootstraps .env from .env.example, prompting for each key with
#      the current value (or NBIO_* env override) as the default
#   3. Creates data/ skeleton (app.db lives here)
#   4. Builds the app + backup images
#   5. Optional Google Drive backup setup — collapses the two-step
#      rclone dance into one paste of the token blob from
#      `rclone authorize "drive"`
#   6. Brings the stack up; polls /healthz; prints URLs
#
# Env overrides (for CI / non-interactive runs):
#   NBIO_NONINTERACTIVE=1   skip all prompts; missing values use defaults
#   NBIO_TZ                 timezone, e.g. Europe/London
#   NBIO_BABY_NAME          baby's display name
#   NBIO_APP_PORT           host port (mapped to container :8000)
#   NBIO_RCLONE_REMOTE      rclone remote name (default: gdrive)
#   NBIO_RCLONE_TOKEN       JSON token blob from `rclone authorize "drive"`
#                           (unset / empty = skip remote backup setup)
#   NBIO_RETAIN_LOCAL       local snapshots to keep
#   NBIO_RETAIN_REMOTE_DAYS purge remote snapshots older than N days
#
# Flags:
#   --dry-run   run steps 1-3 only (no docker build / up). Useful for CI.
#   --help      this help

set -euo pipefail

# ----- args ------------------------------------------------------------------
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --help|-h)
      sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

NONINTERACTIVE=${NBIO_NONINTERACTIVE:-0}

# ----- helpers ---------------------------------------------------------------
info()  { printf '\033[1;34m::\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
err()   { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }

prompt() {
  # prompt KEY DEFAULT DESCRIPTION
  #   resolution order: NBIO_<KEY> env override → user prompt → DEFAULT
  local key="$1" default="$2" desc="$3" override="NBIO_${1}" val=""
  if [[ -n "${!override:-}" ]]; then
    echo "${!override}"; return
  fi
  if (( NONINTERACTIVE )); then
    echo "$default"; return
  fi
  read -r -p "  $desc [$default]: " val
  echo "${val:-$default}"
}

yn() {
  # yn QUESTION DEFAULT(y|n)
  local q="$1" default="${2:-n}" val
  if (( NONINTERACTIVE )); then
    [[ "$default" == "y" ]]; return
  fi
  local hint="[y/N]"; [[ "$default" == "y" ]] && hint="[Y/n]"
  read -r -p "  $q $hint: " val
  val="${val:-$default}"
  [[ "${val,,}" =~ ^y(es)?$ ]]
}

set_env_key() {
  # set_env_key KEY VALUE  — uses | as sed delimiter; values must not contain |
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

# ----- 1. pre-flight ---------------------------------------------------------
info "Pre-flight checks"
if ! command -v docker >/dev/null 2>&1; then
  err "docker not found. Install: https://docs.docker.com/engine/install/"
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  err "docker compose v2 not found. Install the compose plugin."
  exit 1
fi
ok "docker: $(docker --version | awk '{print $3}' | tr -d ,)"
ok "docker compose: $(docker compose version --short)"

# ----- 2. .env bootstrap -----------------------------------------------------
info ".env bootstrap"
if [[ ! -f .env.example ]]; then
  err "No .env.example in $(pwd). Run this from the repo root."
  exit 1
fi
if [[ ! -f .env ]]; then
  cp .env.example .env
  ok "created .env from .env.example"
else
  ok ".env exists — will update keys in place"
fi

current_tz=$(grep -E '^TZ='        .env | head -1 | cut -d= -f2- || echo "Europe/London")
current_bn=$(grep -E '^BABY_NAME=' .env | head -1 | cut -d= -f2- || echo "Baby")
current_ap=$(grep -E '^APP_PORT='  .env | head -1 | cut -d= -f2- || echo "8000")
current_rr=$(grep -E '^RCLONE_REMOTE='     .env | head -1 | cut -d= -f2- || echo "gdrive")
current_rl=$(grep -E '^RETAIN_LOCAL='      .env | head -1 | cut -d= -f2- || echo "7")
current_rd=$(grep -E '^RETAIN_REMOTE_DAYS=' .env | head -1 | cut -d= -f2- || echo "30")

set_env_key TZ                  "$(prompt TZ                  "$current_tz" "Timezone")"
set_env_key BABY_NAME           "$(prompt BABY_NAME           "$current_bn" "Baby's display name")"
set_env_key APP_PORT            "$(prompt APP_PORT            "$current_ap" "Host port")"
set_env_key RCLONE_REMOTE       "$(prompt RCLONE_REMOTE       "$current_rr" "rclone remote name")"
set_env_key RETAIN_LOCAL        "$(prompt RETAIN_LOCAL        "$current_rl" "Local snapshots to keep")"
set_env_key RETAIN_REMOTE_DAYS  "$(prompt RETAIN_REMOTE_DAYS  "$current_rd" "Remote retention (days)")"
ok ".env written"

# Re-read for downstream steps
# shellcheck disable=SC1091
set -a; source .env; set +a

# ----- 3. data/ skeleton -----------------------------------------------------
info "data/ skeleton"
mkdir -p data data/backups data/rclone
ok "data/, data/backups/, data/rclone/"

# ----- dry-run early exit ----------------------------------------------------
if (( DRY_RUN )); then
  info "--dry-run set — stopping before docker build."
  ok "dry run complete. Inspect ./.env and ./data/ to verify."
  exit 0
fi

# ----- 4. build images -------------------------------------------------------
info "Building images (this can take a few minutes on first run)"
docker compose build
ok "images built"

# ----- 5. rclone Drive bootstrap --------------------------------------------
info "Google Drive backup setup"
if [[ -f data/rclone/rclone.conf ]]; then
  ok "data/rclone/rclone.conf already exists — skipping"
else
  token=""
  if [[ -n "${NBIO_RCLONE_TOKEN:-}" ]]; then
    token="$NBIO_RCLONE_TOKEN"
  elif yn "Set up Google Drive backup now?" n; then
    cat <<EOF

  ON A MACHINE WITH A BROWSER (laptop, phone), run:
    rclone authorize "drive"
  Sign in, allow access, and copy the JSON blob it prints to stdout.

EOF
    read -r -p "  Paste the JSON token blob here (single line): " token
  fi

  if [[ -n "$token" ]]; then
    info "Persisting rclone config for remote: ${RCLONE_REMOTE:-gdrive}"
    docker compose run --rm backup rclone --config /config/rclone.conf \
      config create "${RCLONE_REMOTE:-gdrive}" drive \
        config_is_local=false \
        token="$token" \
      >/dev/null
    info "Verifying — listing remote (expect no error):"
    if docker compose run --rm backup rclone --config /config/rclone.conf \
         lsd "${RCLONE_REMOTE:-gdrive}:" >/dev/null 2>&1; then
      ok "rclone Drive set up; nightly remote backup enabled"
    else
      warn "rclone could not list ${RCLONE_REMOTE:-gdrive}: — check the token"
      warn "Local backups will still run; re-run setup to retry the remote."
    fi
  else
    warn "No token provided — backups will be LOCAL-ONLY in ./data/backups/"
    warn "Re-run setup any time to bootstrap remote backup."
  fi
fi

# ----- 6. Tailscale serve hook (issue #5) -----------------------------------
# When #5 lands, this block will optionally run `tailscale serve --bg
# https://localhost:${APP_PORT}` so the app is reachable on HTTPS via
# MagicDNS. Hostname source priority: NBIO_TS_HOSTNAME env → prompt →
# autodetect via `tailscale status --json`. For now: nothing.

# ----- 7. bring up + healthz -------------------------------------------------
info "Starting the stack"
docker compose up -d
ok "containers running"

info "Waiting for /healthz (up to 30s)"
healthy=0
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${APP_PORT:-8000}/healthz" >/dev/null 2>&1; then
    healthy=1; break
  fi
  sleep 1
done
if (( healthy )); then
  ok "/healthz responded"
else
  warn "/healthz did not respond within 30s — check 'docker compose logs app'"
fi

# ----- 8. summary ------------------------------------------------------------
info "Done."
echo ""
echo "  App:       http://localhost:${APP_PORT:-8000}"
if command -v tailscale >/dev/null 2>&1; then
  ts_host=$(tailscale status --json 2>/dev/null \
            | grep -oE '"DNSName":[[:space:]]*"[^"]+"' \
            | head -1 \
            | sed -E 's/.*"([^"]+)".*/\1/' \
            | sed -E 's/\.$//' || true)
  if [[ -n "${ts_host:-}" ]]; then
    echo "  Tailscale: http://${ts_host}:${APP_PORT:-8000}"
    echo "             (HTTPS via 'tailscale serve' will land in issue #5)"
  fi
fi
echo ""
echo "  Force a backup right now:   make backup"
echo "  Live logs:                  make logs"
echo "  Stop the stack:             make down"
echo ""
echo "  Data lives in ./data/ — back this directory up like /etc."
