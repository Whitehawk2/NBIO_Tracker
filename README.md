# NBIO Tracker

A small, self-hosted, **shared** newborn tracker for **N**ewborn **B**reastfeeds,
wees and poos. Built for two sleep-deprived parents on phones, served from
your home server over Tailscale.

- 🤱💦💩 One-tap logging with a smart time picker (`now`, `-5m`, `-15m`, `-30m`, `-1h`, `-2h`, or any time you pick)
- 👥 Live sync between phones via SSE; cross-parent duplicate prompts
- 📵 Works offline — entries queue on the device and flush when back online
- 🌙 Auto dark mode at night (sunset → sunrise) so you're not blinded at 3am
- 📊 Today summary, 7-day timeline + heatmap, 14-day totals (copy-to-text for the paediatrician)
- 📥 Installable as a PWA (Add to Home Screen on iOS/Android)
- 💾 Nightly SQLite snapshot → Google Drive via rclone, with local rotation

No accounts. The network (Tailscale) is the perimeter.

## Quick start

Requirements: Docker + Docker Compose on the host. A Tailscale-connected
home server is the intended deployment.

```bash
cp .env.example .env       # edit BABY_NAME, TZ if you like
docker compose up -d --build
```

Open `http://<your-host>:8000` over Tailscale. On first launch each phone
picks a colour + (optional) name — that's the "who logged what" indicator
on every row.

### Data layout

```
data/
  app.db            ← SQLite (WAL); local fs only, never on NFS/SMB
  backups/          ← gzipped nightly snapshots (rotated, keep N)
  rclone/           ← rclone.conf with Google Drive token
```

## Setting up Google Drive backups

The backup container runs nightly at 03:00 local time. Without an rclone
config it still produces local snapshots; remote upload requires a one-time
auth dance.

1. **Get a Drive OAuth token on any machine with a browser:**
   ```bash
   rclone authorize "drive"
   ```
   Copy the JSON token it prints.

2. **Persist the config in the container's mount:**
   ```bash
   docker compose run --rm backup rclone --config /config/rclone.conf \
     config create gdrive drive \
     config_is_local=false \
     token='PASTE_JSON_HERE'
   ```

3. **Verify:**
   ```bash
   docker compose run --rm backup rclone --config /config/rclone.conf lsd gdrive:
   docker compose exec backup /usr/local/bin/backup.sh   # force a backup now
   ```

`.env` controls retention:

- `RETAIN_LOCAL` — number of local snapshots to keep (default 7)
- `RETAIN_REMOTE_DAYS` — purge remote snapshots older than N days (default 30)

## Restoring from a backup

```bash
docker compose stop app

# from a local snapshot
docker compose run --rm backup /usr/local/bin/restore.sh /backups/app-YYYYMMDD-HHMM.db.gz

# or pull from Google Drive first
docker compose run --rm backup /usr/local/bin/restore.sh remote app-YYYYMMDD-HHMM.db.gz

docker compose start app
```

The previous `data/app.db` is renamed to `app.db.broken` (kept for safety).

## How it works (briefly)

- **FastAPI + SQLite (WAL) + Jinja2** in one container. No JS build step.
- **Offline writes**: each submit gets a client-side `idempotency_key`
  (UUID). If the network is down, the request is held in IndexedDB and
  flushed on `visibilitychange` / `online` / a 30s interval (iOS-safe —
  Background Sync isn't supported there). Server is idempotent: replays
  return `already_exists` instead of creating duplicates.
- **Cross-parent duplicates**: when two phones log the same type within
  ±2 minutes, the server still inserts (accept-by-default) but returns a
  `created_possible_duplicate` payload so the second phone can prompt
  "looks like Mum just logged this — delete mine?".
- **Live sync** via Server-Sent Events. Reconnects use `Last-Event-ID` to
  replay missed events (capped at 500; falls back to a full re-fetch
  beyond that).

## Gotchas worth knowing

- **Put `data/` on a local filesystem.** SQLite locking on NFS/SMB is
  unreliable. Backups *to* a NAS are fine.
- **iOS PWA** has no Background Sync. The page flushes when it becomes
  visible — works as long as a parent opens the app at least every few
  days (which, with a newborn, they do).
- **Reverse proxies and SSE**: Tailscale itself is transparent TCP and
  fine, but if you front this with Caddy/Nginx, disable response buffering
  for `/api/stream`. The server already sends `X-Accel-Buffering: no`.

## Branch / development notes

- Default branch for ongoing work: `claude/newborn-tracker-app-PoMGY`
- Local dev without Docker:
  ```bash
  cd app && pip install -e .
  DB_PATH=/tmp/nbio.db uvicorn nbio.main:app --reload --host 0.0.0.0 --port 8000
  ```
