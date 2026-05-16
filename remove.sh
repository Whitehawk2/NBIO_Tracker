#!/usr/bin/env bash
# NBIO Tracker — uninstall / cleanup.
#
# Safe by default: stops containers, removes locally-built images. Does NOT
# touch .env or data/ unless you ask. The data/ directory contains the
# SQLite database and all local backup snapshots — removing it is
# IRREVERSIBLE and requires both a flag and a confirmation.
#
# Use cases:
#   Failed install cleanup:        ./remove.sh
#   Full uninstall, keep data:     ./remove.sh --env
#   Wipe everything:               ./remove.sh --env --data --yes
#   Stop only, keep images:        ./remove.sh --keep-images
#
# Flags:
#   --env / --remove-env       remove .env too
#   --data / --remove-data     remove ./data/ too — DESTRUCTIVE
#   --keep-images              don't remove locally-built docker images
#   --yes / -y                 skip confirmations (CI mode)
#   --help / -h                this help
#
# Env overrides (for CI):
#   NBIO_REMOVE_ENV=1          same as --env
#   NBIO_REMOVE_DATA=1         same as --data
#   NBIO_KEEP_IMAGES=1         same as --keep-images
#   NBIO_NONINTERACTIVE=1      same as --yes (still requires --data flag
#                              to wipe data/ — env var alone won't do it)

set -euo pipefail

REMOVE_ENV=${NBIO_REMOVE_ENV:-0}
REMOVE_DATA=${NBIO_REMOVE_DATA:-0}
KEEP_IMAGES=${NBIO_KEEP_IMAGES:-0}
YES=${NBIO_NONINTERACTIVE:-0}

for arg in "$@"; do
  case "$arg" in
    --env|--remove-env)   REMOVE_ENV=1 ;;
    --data|--remove-data) REMOVE_DATA=1 ;;
    --keep-images)        KEEP_IMAGES=1 ;;
    --yes|-y)             YES=1 ;;
    --help|-h)
      sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# ----- helpers ---------------------------------------------------------------
info()  { printf '\033[1;34m::\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
err()   { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }

yn() {
  local q="$1" default="${2:-n}" val
  if (( YES )); then
    [[ "$default" == "y" ]]; return
  fi
  local hint="[y/N]"; [[ "$default" == "y" ]] && hint="[Y/n]"
  read -r -p "  $q $hint: " val
  val="${val:-$default}"
  [[ "${val,,}" =~ ^y(es)?$ ]]
}

# ----- 1. containers + images ------------------------------------------------
info "Stopping containers"
if ! command -v docker >/dev/null 2>&1; then
  warn "docker not on PATH — skipping container removal"
elif ! docker compose version >/dev/null 2>&1; then
  warn "docker compose v2 not available — skipping container removal"
elif [[ ! -f docker-compose.yml ]]; then
  warn "no docker-compose.yml in $(pwd) — skipping container removal"
else
  args=(down --remove-orphans)
  if (( KEEP_IMAGES )); then
    info "keeping locally-built images (--keep-images)"
  else
    args+=(--rmi local)
  fi
  if docker compose "${args[@]}"; then
    ok "containers stopped and removed"
    (( KEEP_IMAGES )) || ok "locally-built images removed"
  else
    warn "docker compose down reported an error — continuing"
  fi
fi

# ----- 2. .env ---------------------------------------------------------------
if [[ -f .env ]]; then
  if (( REMOVE_ENV )) || yn "Remove .env? (config only — setup.sh can recreate it)" n; then
    rm -f .env
    ok ".env removed"
  else
    ok ".env preserved"
  fi
else
  ok "no .env present"
fi

# ----- 3. data/ — destructive ------------------------------------------------
if [[ -d data ]] && [[ "$(find data -mindepth 1 -maxdepth 1 -not -name .gitkeep | head -1)" ]]; then
  if (( REMOVE_DATA )); then
    proceed=0
    if (( YES )); then
      proceed=1
    else
      cat <<EOF

  ⚠️  About to delete ./data/ — this is IRREVERSIBLE.

  Contents to be removed:
    - data/app.db                 the SQLite database (every event ever logged)
    - data/backups/*.db.gz        every local snapshot
    - data/rclone/rclone.conf     the Google Drive auth token

  Remote Google Drive snapshots will NOT be touched. Delete them manually
  from Drive if you want them gone too.

EOF
      yn "Type 'y' to confirm — anything else aborts data removal" n && proceed=1
    fi
    if (( proceed )); then
      # Keep data/.gitkeep so a future setup.sh re-run has the mount point
      find data -mindepth 1 -not -name .gitkeep -delete
      ok "data/ contents removed (.gitkeep preserved)"
    else
      ok "data/ preserved"
    fi
  else
    info "data/ kept. Pass --data to also remove it (destroys the SQLite DB)."
  fi
else
  ok "no data to remove"
fi

# ----- 4. Tailscale serve teardown (issue #5) -------------------------------
# When #5 lands, this block will run `tailscale serve --bg --remove` (or
# equivalent) so the HTTPS proxy registration is also undone. No-op today.

# ----- summary ---------------------------------------------------------------
info "Done."
echo ""
echo "  Re-install: ./setup.sh"
if [[ -d data ]] && [[ "$(find data -mindepth 1 -maxdepth 1 -not -name .gitkeep | head -1)" ]]; then
  echo "  Note: ./data/ still has files — pass --data to remove them too."
fi
