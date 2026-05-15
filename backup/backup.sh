#!/bin/bash
# NBIO nightly backup: SQLite online snapshot -> gzip -> rclone copy to remote.
# Variables (from env): RCLONE_REMOTE, RETAIN_LOCAL, RETAIN_REMOTE_DAYS
set -euo pipefail

RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive}"
RETAIN_LOCAL="${RETAIN_LOCAL:-7}"
RETAIN_REMOTE_DAYS="${RETAIN_REMOTE_DAYS:-30}"

DB_PATH="/data/app.db"
BACKUPS="/backups"
CONFIG="/config/rclone.conf"

mkdir -p "${BACKUPS}"

if [ ! -f "${DB_PATH}" ]; then
  echo "[$(date -u +%FT%TZ)] db not found at ${DB_PATH}; nothing to back up" >&2
  exit 0
fi

TS=$(date -u +%Y%m%d-%H%M)
SNAP="${BACKUPS}/app-${TS}.db"

echo "[$(date -u +%FT%TZ)] snapshotting ${DB_PATH} -> ${SNAP}"
sqlite3 "${DB_PATH}" ".backup '${SNAP}'"
gzip -9f "${SNAP}"

echo "[$(date -u +%FT%TZ)] pruning local snapshots, keeping ${RETAIN_LOCAL}"
ls -1t "${BACKUPS}"/app-*.db.gz 2>/dev/null | tail -n +$((RETAIN_LOCAL + 1)) | xargs -r rm -f

if [ -f "${CONFIG}" ]; then
  echo "[$(date -u +%FT%TZ)] uploading ${SNAP}.gz -> ${RCLONE_REMOTE}:nbio/"
  rclone --config "${CONFIG}" copy "${SNAP}.gz" "${RCLONE_REMOTE}:nbio/" \
    --transfers=1 --checkers=1 --retries 3

  echo "[$(date -u +%FT%TZ)] pruning remote snapshots older than ${RETAIN_REMOTE_DAYS}d"
  rclone --config "${CONFIG}" delete --min-age "${RETAIN_REMOTE_DAYS}d" "${RCLONE_REMOTE}:nbio/" || true
else
  echo "[$(date -u +%FT%TZ)] no rclone config at ${CONFIG}; skipping remote upload (local snapshot kept)" >&2
fi

echo "[$(date -u +%FT%TZ)] done"
