#!/bin/bash
# NBIO restore helper.
# Usage:
#   restore.sh /backups/app-20260515-0300.db.gz   # restore from local snapshot
#   restore.sh remote app-20260515-0300.db.gz     # fetch from rclone remote then restore
set -euo pipefail

DB_PATH="/data/app.db"
CONFIG="/config/rclone.conf"
RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive}"

usage() {
  echo "usage: restore.sh <path-to-snapshot.db.gz>"
  echo "       restore.sh remote <snapshot-name.db.gz>"
  exit 2
}

if [ $# -lt 1 ]; then usage; fi

if [ "$1" = "remote" ]; then
  [ $# -eq 2 ] || usage
  [ -f "${CONFIG}" ] || { echo "no rclone config at ${CONFIG}"; exit 1; }
  mkdir -p /backups
  rclone --config "${CONFIG}" copy "${RCLONE_REMOTE}:nbio/$2" /backups/
  SRC="/backups/$2"
else
  SRC="$1"
fi

[ -f "${SRC}" ] || { echo "snapshot not found: ${SRC}"; exit 1; }

echo "Restoring ${SRC} -> ${DB_PATH}"
echo "STOP the app container before continuing."
echo "Existing ${DB_PATH} will be moved to ${DB_PATH}.broken"
read -r -p "Continue? [y/N] " ans
[ "${ans}" = "y" ] || { echo "aborted"; exit 1; }

if [ -f "${DB_PATH}" ]; then mv -f "${DB_PATH}" "${DB_PATH}.broken"; fi

TMP="${DB_PATH}.restoring"
gunzip -c "${SRC}" > "${TMP}"
mv -f "${TMP}" "${DB_PATH}"
echo "Done. Start the app container."
