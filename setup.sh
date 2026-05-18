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
#   NBIO_APP_BIND           host interface (default 127.0.0.1; 0.0.0.0 for LAN)
#   NBIO_RCLONE_REMOTE      rclone remote name (default: gdrive)
#   NBIO_RCLONE_TOKEN       JSON token blob from `rclone authorize "drive"`
#                           (unset / empty = skip remote backup setup)
#   NBIO_RETAIN_LOCAL       local snapshots to keep
#   NBIO_RETAIN_REMOTE_DAYS purge remote snapshots older than N days
#   NBIO_TS_HOSTNAME        Tailscale hostname for the printed URL
#                           (otherwise autodetected from `tailscale status`)
#   NBIO_VERBOSE            =1 to trace the Tailscale + rclone blocks
#                           via `set -x`. Same as --verbose.
#
# Flags:
#   --dry-run   run steps 1-3 only (no docker build / up). Useful for CI.
#   --verbose   echo every command the script runs in the Tailscale +
#               rclone blocks (set -x within those sections). Same as
#               NBIO_VERBOSE=1.
#   --help      this help

set -euo pipefail

# ----- args ------------------------------------------------------------------
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --verbose) NBIO_VERBOSE=1 ;;
    --help|-h)
      sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

NONINTERACTIVE=${NBIO_NONINTERACTIVE:-0}
VERBOSE=${NBIO_VERBOSE:-0}

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

# Probe whether `tailscale` is installed AND signed in AND usable for serve.
# Sets TS_PREFIX="" (no sudo needed) or "sudo" (escalation required).
# Returns 1 when Tailscale is unavailable or sudo would block.
TS_PREFIX=""
probe_tailscale() {
  TS_PREFIX=""
  command -v tailscale >/dev/null 2>&1 || return 1
  tailscale status >/dev/null 2>&1 || return 1
  if tailscale serve status >/dev/null 2>&1; then
    return 0
  fi
  command -v sudo >/dev/null 2>&1 || return 1
  if (( NONINTERACTIVE )); then
    sudo -n tailscale serve status >/dev/null 2>&1 || return 1
  fi
  TS_PREFIX="sudo"
  return 0
}

# Autodetect Tailscale hostname for the printed URL.
# Priority: NBIO_TS_HOSTNAME env → interactive prompt with autodetect default
# → autodetect alone in non-interactive mode.
ts_hostname() {
  if [[ -n "${NBIO_TS_HOSTNAME:-}" ]]; then
    echo "$NBIO_TS_HOSTNAME"; return
  fi
  local detected
  detected=$(tailscale status --json 2>/dev/null \
             | grep -oE '"DNSName":[[:space:]]*"[^"]+"' \
             | head -1 | sed -E 's/.*"([^"]+)".*/\1/' \
             | sed -E 's/\.$//' || true)
  if (( NONINTERACTIVE )); then
    echo "$detected"; return
  fi
  local val
  read -r -p "  Tailscale hostname for the printed URL [${detected}]: " val
  echo "${val:-$detected}"
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
current_ab=$(grep -E '^APP_BIND='  .env | head -1 | cut -d= -f2- || echo "127.0.0.1")
current_rr=$(grep -E '^RCLONE_REMOTE='     .env | head -1 | cut -d= -f2- || echo "gdrive")
current_rl=$(grep -E '^RETAIN_LOCAL='      .env | head -1 | cut -d= -f2- || echo "7")
current_rd=$(grep -E '^RETAIN_REMOTE_DAYS=' .env | head -1 | cut -d= -f2- || echo "30")

set_env_key TZ                  "$(prompt TZ                  "$current_tz" "Timezone")"
set_env_key BABY_NAME           "$(prompt BABY_NAME           "$current_bn" "Baby's display name")"
set_env_key APP_PORT            "$(prompt APP_PORT            "$current_ap" "Host port")"
set_env_key APP_BIND            "$(prompt APP_BIND            "$current_ab" "Host bind (127.0.0.1 = Tailscale-only; 0.0.0.0 = LAN)")"
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

# ----- 6. bring up + healthz -------------------------------------------------
info "Starting the stack"
docker compose up -d
ok "containers running (port bound to ${APP_BIND:-127.0.0.1}:${APP_PORT:-8000})"

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

# ----- 7. Tailscale serve (HTTPS via MagicDNS) ------------------------------
TS_REGISTERED=0
TS_HOST=""
if probe_tailscale; then
  TS_HOST=$(ts_hostname)
  info "Registering with tailscale serve (HTTPS via MagicDNS)"
  if (( ${#TS_PREFIX} )); then
    info "  (using sudo — you may be prompted for a password)"
  fi
  # Echo the exact command before running so a failure isn't opaque.
  # `→` matches the success-line style used elsewhere in setup output.
  TS_CMD="tailscale serve --bg --https=443 http://localhost:${APP_PORT:-8000}"
  echo "  → ${TS_PREFIX:+sudo }${TS_CMD}"
  # Capture stderr so we can surface the daemon's reason on failure.
  (( VERBOSE )) && set -x
  TS_ERR=$($TS_PREFIX tailscale serve --bg --https=443 \
       "http://localhost:${APP_PORT:-8000}" 2>&1 >/dev/null) && TS_RC=0 || TS_RC=$?
  (( VERBOSE )) && set +x
  if (( TS_RC == 0 )); then
    TS_REGISTERED=1
    ok "tailscale serve registered → https://${TS_HOST:-<your-tailnet-host>}/"
  else
    warn "tailscale serve registration failed."
    TS_REASON=$(printf '%s\n' "$TS_ERR" | head -1)
    if [[ -n "$TS_REASON" ]]; then
      warn "  reason: $TS_REASON"
    fi
    warn "  Inspect:    sudo tailscale serve status"
    warn "  Re-try:     sudo ${TS_CMD}"
    warn "  Clear all:  sudo tailscale serve reset"
    warn "Your tailnet may need MagicDNS + HTTPS Certificates enabled in the admin panel."
    warn "App is still reachable locally on http://localhost:${APP_PORT:-8000}."
  fi
else
  info "Tailscale not detected (or not signed in / no privileges) — skipping HTTPS setup."
fi

# ----- 8. summary ------------------------------------------------------------
info "Done."
echo ""
if (( TS_REGISTERED )); then
  echo "  App:       https://${TS_HOST:-<your-tailnet-host>}/   (via tailscale serve)"
elif [[ -n "$TS_HOST" ]]; then
  echo "  App:       http://localhost:${APP_PORT:-8000}"
  echo "  Tailscale: http://${TS_HOST}:${APP_PORT:-8000}   (LAN-bound; HTTPS setup failed)"
else
  echo "  App:       http://localhost:${APP_PORT:-8000}"
  if [[ "${APP_BIND:-127.0.0.1}" == "127.0.0.1" ]]; then
    echo "             (bound to localhost only — set APP_BIND=0.0.0.0 in .env for LAN)"
  fi
fi
echo ""
echo "  Force a backup right now:   make backup"
echo "  Live logs:                  make logs"
echo "  Stop the stack:             make down"
echo "  Uninstall:                  ./remove.sh"
echo ""
echo "  Data lives in ./data/ — back this directory up like /etc."
