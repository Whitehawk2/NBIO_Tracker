# NBIO Tracker

A small, self-hosted, **shared** newborn tracker for **N**ewborn **B**reastfeeds,
wees and poos. Built for two sleep-deprived parents on phones, served from your
home server over Tailscale.

- 🤱💦💩 One-tap logging with a smart time-chip picker (`now`, `-5m`, `-15m`, `-30m`, `-1h`, `-2h`, or any time you pick)
- 👥 Live sync between phones via SSE; cross-parent duplicate prompts (±2 min)
- 📵 Works offline — entries queue on the device and flush when back online
- 🌙 Auto dark mode at night (19:00–07:00 + `prefers-color-scheme`) so you're not blinded at 3am
- 📊 Today summary, 7-day timeline + heatmap, daily totals
- 📥 Installable as a PWA (Android & iOS Add to Home Screen)
- 💾 Nightly SQLite snapshot → Google Drive via rclone, with local rotation

No accounts. The network (Tailscale) is the perimeter.

> **Platform focus.** This README is Android-first because that's the household
> target. iOS works too and is called out where the behaviour differs (notably
> around offline sync — see [Offline queue](#offline-queue)).

---

## Contents

1. [Architecture at a glance](#architecture-at-a-glance)
2. [Quick start](#quick-start)
3. [Server setup](#server-setup)
4. [Tailscale integration](#tailscale-integration)
5. [Installing on your phone](#installing-on-your-phone)
6. [First-launch onboarding](#first-launch-onboarding)
7. [Offline queue](#offline-queue)
8. [Google Drive backups](#google-drive-backups)
9. [Restoring from a backup](#restoring-from-a-backup)
10. [Reports](#reports)
11. [Troubleshooting](#troubleshooting)
12. [Development notes](#development-notes)
13. [How it works (internals)](#how-it-works-internals)

---

## Architecture at a glance

```
   Android / iOS phones (PWA)
   │  HTMX UI, IndexedDB outbox, Service Worker
   │
   │   HTTP + SSE  (Tailscale-only, no auth)
   ▼
┌──────────────────────────────────────────┐
│  nbio-app  (FastAPI + SQLite WAL)        │
│   /api/events  /api/stream  /api/devices │
└─────────────┬────────────────────────────┘
              │  shares ./data/app.db
              ▼
┌──────────────────────────────────────────┐
│  nbio-backup  (alpine + sqlite + rclone) │
│   nightly .backup → gzip → Google Drive  │
└──────────────────────────────────────────┘
```

Two containers, one bind-mounted `./data/` directory, served on a single port.

---

## Quick start

Requirements: Docker + Docker Compose v2 on the host. A Tailscale-connected
home server is the intended deployment, but any reachable host works.

```bash
git clone https://github.com/Whitehawk2/NBIO_Tracker.git
cd NBIO_Tracker
./setup.sh             # or: make setup
```

`setup.sh` is idempotent and walks you through:
- `.env` (timezone, baby name, port, …) — one prompt per key with sensible defaults
- `data/` directory skeleton
- image build
- optional Google Drive backup bootstrap (paste the JSON blob from
  `rclone authorize "drive"` once; the script handles the rest)
- `docker compose up -d` + healthz poll

CI / fully-automated installs: set `NBIO_NONINTERACTIVE=1` plus the relevant
`NBIO_*` env vars (`NBIO_TZ`, `NBIO_BABY_NAME`, `NBIO_APP_PORT`,
`NBIO_RCLONE_TOKEN`, …). See `./setup.sh --help` for the full list.

**Undoing it:** `./remove.sh` (or `make remove`) cleanly stops the stack
and removes the locally-built images. By default it preserves `.env` and
`./data/` — the data directory contains the SQLite DB and every backup
snapshot, so removing it requires `--data` plus a confirmation. Full wipe:
`./remove.sh --env --data --yes`. See `./remove.sh --help`.

> **Nix users:** `./setup.sh` is for the Docker path only. The Nix flake
> (issue [#7](https://github.com/Whitehawk2/NBIO_Tracker/issues/7)) will
> ship a `nix profile install`-ready package and a NixOS module that
> replace this whole setup — ignore the script and use those instead.

Verify it's up:

```bash
curl http://localhost:8000/healthz     # → {"status":"ok"}
make status                            # both nbio-app and nbio-backup running
make logs                              # follow live logs (Ctrl-C to exit)
```

Then open `http://<host>:8000` in a browser. On a phone, see
[Installing on your phone](#installing-on-your-phone).

### Manual setup (if you'd rather not use the script)

```bash
cp .env.example .env       # edit BABY_NAME, TZ, APP_PORT to taste
docker compose up -d --build
```

For Google Drive backups, see [Google Drive backups](#google-drive-backups)
below — it's a two-step manual dance the script collapses into one paste.

`.env` knobs:

| Variable | Default | Meaning |
|---|---|---|
| `TZ` | `Europe/London` | Timezone for both containers and cron |
| `BABY_NAME` | `Baby` | Display name; seeded on first boot |
| `APP_PORT` | `8000` | Host port (mapped to container `:8000`) |
| `APP_BIND` | `127.0.0.1` | Host interface to bind. `127.0.0.1` = Tailscale-only (no LAN). `0.0.0.0` to expose on LAN. |
| `RCLONE_REMOTE` | `gdrive` | Name of the rclone remote (see [backups](#google-drive-backups)) |
| `RETAIN_LOCAL` | `7` | Local snapshots to keep in `data/backups/` |
| `RETAIN_REMOTE_DAYS` | `30` | Purge remote snapshots older than N days |

---

## Server setup

### Install Docker

On Debian/Ubuntu:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # so you don't need sudo for compose
# log out and back in for the group change to apply
```

On Fedora/RHEL: `sudo dnf install docker-ce docker-ce-cli containerd.io
docker-buildx-plugin docker-compose-plugin`. On Raspberry Pi OS the `get.docker.com`
script works fine.

Make Docker start at boot (it's usually enabled already):

```bash
sudo systemctl enable --now docker
```

### Pick a location

Convention is `/opt/nbio` for the repo and bind-mounted data:

```bash
sudo mkdir -p /opt/nbio && sudo chown "$USER" /opt/nbio
cd /opt/nbio
git clone https://github.com/Whitehawk2/NBIO_Tracker.git .
```

The `./data/` subdirectory holds the SQLite database, local backup snapshots,
and the rclone config — back it up like you'd back up `/etc`.

### Autostart on reboot

`restart: unless-stopped` is set on both services in `docker-compose.yml`, so
once Docker is enabled at boot the stack comes back automatically. If you want
explicit lifecycle management, drop a tiny systemd unit at
`/etc/systemd/system/nbio.service`:

```ini
[Unit]
Description=NBIO Tracker (docker compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/nbio
ExecStart=/usr/bin/docker compose up -d --build
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl enable --now nbio`.

### Changing the port

Set `APP_PORT=9090` in `.env` and `docker compose up -d` — the host-side port
changes, the container still listens on `:8000` internally.

If you bind to `127.0.0.1` so the port isn't exposed on your LAN at all (and is
only reachable over Tailscale via `tailscale serve`, see next section), edit
`docker-compose.yml`:

```yaml
ports:
  - "127.0.0.1:${APP_PORT:-8000}:8000"
```

### Inspecting logs

```bash
docker compose logs -f app                  # live app logs
docker compose logs --since 1h backup       # last hour of backup container
docker compose exec backup tail -f /var/log/backup.log   # backup cron output
```

### Upgrading

```bash
cd /opt/nbio
git pull
docker compose up -d --build
```

The database is in a bind-mounted volume (`./data/app.db`); rebuilding
containers does not touch it. Schema migrations run automatically on app start.

### Stopping cleanly

```bash
docker compose down     # stops both containers; data persists
```

`docker compose down -v` would remove anonymous volumes — we don't use any, so
this is harmless, but stick to plain `down` to be safe.

---

## Tailscale integration

NBIO has **no auth**. The threat model assumes only your tailnet can reach it.
Three deployment patterns, ordered by ease:

### Pattern A — Raw HTTP on tailnet (simplest)

1. Install Tailscale on the host: `curl -fsSL https://tailscale.com/install.sh | sh`
2. `sudo tailscale up` (sign in once).
3. Find the host's tailnet name: `tailscale status` — say it's `homepi`.
4. Open `http://homepi:8000` on any device in your tailnet.

Works on day one. Downside: HTTP only. Most PWA features are fine over HTTP on
a private network, but **service workers require either `https://` or
`http://localhost`**, so Pattern A means the PWA install / offline cache only
works if you happen to be browsing the box itself. Not what you want.

### Pattern B — `tailscale serve` for HTTPS via MagicDNS (recommended, automated)

This gives you `https://homepi.<your-tailnet>.ts.net` with a Let's Encrypt cert
issued automatically by Tailscale. Service workers and PWA install work
everywhere. Both parents' phones reach the same hostname.

**`./setup.sh` does this for you.** When Tailscale is installed and signed
in, the script runs the equivalent of:

```bash
sudo tailscale serve --bg --https=443 http://localhost:8000
```

and prints the resulting `https://…ts.net/` URL in its summary. `./remove.sh`
runs `tailscale serve reset` to clear the registration symmetrically.

This pairs with the default `APP_BIND=127.0.0.1` in `.env` — the raw port is
bound only to localhost, so the **only** path in from another device is
through the Tailscale-served HTTPS endpoint.

To override the auto-detected hostname (rare; only useful for custom MagicDNS
aliases), set `NBIO_TS_HOSTNAME=foo` before running `./setup.sh`.

If you want to do it manually instead (e.g. the script can't get sudo):

```bash
sudo tailscale serve --bg --https=443 http://localhost:8000
sudo tailscale serve status     # verify
```

### Pattern C — `tailscale funnel` (NOT recommended)

`tailscale funnel` exposes the service to the public internet. **Don't.** This
app has no auth. Funnel is intentionally excluded from the threat model.

### Tailscale ACL example (optional)

Default tailnets let all your devices reach all your services — fine for a
two-person household. If you've added family or friends to the tailnet and want
to scope NBIO to just the two parents, add an ACL group:

```jsonc
// in your Tailscale admin → Access Controls
{
  "groups": {
    "group:parents": ["alice@example.com", "bob@example.com"]
  },
  "acls": [
    // existing rules…
    {
      "action": "accept",
      "src": ["group:parents"],
      "dst": ["homepi:8000", "homepi:443"]
    }
  ]
}
```

### Tailscale + Android

Install the Tailscale app from Play Store, sign in, leave it running. The VPN
icon will sit in the status bar. Verify with the in-app "ping" or just by
loading the NBIO URL in Chrome.

### Tailscale + iOS

Same: Tailscale app → sign in → enable. iOS only allows one VPN profile active
at a time, so if you use another VPN you'll have to toggle.

---

## Installing on your phone

### Android (primary)

You want the PWA installed so it gets its own icon, full-screen mode, and
Chrome's Background Sync API for offline-flush.

1. **Make sure you can reach the app over Tailscale** (Pattern B above gives
   you `https://homepi.<your-tailnet>.ts.net`).
2. Open the URL in **Chrome** (Edge and Brave also work; Firefox's PWA install
   on Android is limited and not recommended for this app).
3. Chrome usually shows a small "Install app" prompt at the bottom after a few
   seconds. If it doesn't, open the **⋮ menu (top right) → "Install app"** or
   **"Add to Home screen"** (wording varies by Chrome version).
4. Confirm. An "NBIO" icon appears in your app drawer.
5. **Launch from that icon** — not from the Chrome tab. Launching from the
   home-screen icon is what enables full-screen, the install shortcut, and
   most importantly enables Background Sync for offline flushes.

What you should see after install:
- Full-screen, no browser chrome.
- Appears in Android's recents view as its own app.
- Long-pressing the icon shows app shortcuts (Android 7.1+).

If the "Install app" option doesn't appear, see
[Troubleshooting → install option missing](#install-option-missing).

### iOS (secondary)

1. Open the URL in **Safari** (not Chrome — iOS Chrome can't install PWAs).
2. Tap the **Share** icon (square with up-arrow) → scroll down →
   **Add to Home Screen** → **Add**.
3. Launch from the home-screen icon.

iOS limitations to be aware of:
- **No Background Sync.** Queued offline writes flush only when you reopen the
  app. In practice with a newborn you do that every two hours anyway.
- **Storage eviction** if the app isn't opened for ~7 days. Again, fine for
  this use case.
- Push notifications need iOS 16.4+ and are not implemented in v1.

### What works without installing

If you just open the URL in a browser without installing, you still get:
- The full UI and live sync.
- Auto dark mode.
- Logging, editing, deletes, undo.

You **lose**:
- Full-screen.
- Reliable offline behaviour (service worker caches the shell, but installed
  PWAs are more resilient to browser cache eviction).
- The home-screen icon convenience that matters most at 3am.

So: install it.

---

## First-launch onboarding

On the very first launch of each phone, a small modal asks:

1. **"Whose phone is this?"** — optional name (free text, "Mum" / "Dad" / a
   first name).
2. **Pick a colour** — six swatches. The colour is the trailing dot on every
   event row, and the answer to "did you already log this?" at a glance.
   Mum and Dad should pick different ones; the app doesn't enforce it.

Stored in `localStorage` and synced to the server as a `device` record so the
other phone sees who logged what. No password, no email, no account.

Change later: clear site data and reopen, or open DevTools → Application →
Local Storage → remove `nbio.device_color` and refresh.

---

## Offline queue

This is the headline correctness feature: a parent in a basement room or on a
patchy connection can keep logging and nothing is lost.

### What you see

- Tap a tile → modal → Submit. The row appears immediately, even if offline.
  Offline rows have a subtle "pending" style.
- A small badge in the header — e.g. `2 ↑` — tells you how many writes are
  still queued. Zero state is invisible (no nagging when fine).
- A small connection dot: green = SSE live-sync connected, grey = polling,
  orange = offline.
- When the queue drains successfully, badges and pending styling vanish.

### What's happening under the hood

1. The UI generates a fresh `idempotency_key` (UUID) for every submit.
2. An optimistic row is inserted into the list and the request is sent.
3. If the network is up the server returns the canonical row, the client
   reconciles, done.
4. If the request fails (no network, server down, Tailscale paused), the page
   stores `{idem, method, url, body, ts}` in an IndexedDB store called
   `nbio.outbox` and keeps the optimistic row marked pending.
5. The flush runs whenever **any** of these triggers fires:
   - `visibilitychange` — every time you reopen the tab/app.
   - `online` — when the OS reports network back.
   - 30 s `setInterval` while the app is visible.
   - **Android only:** the Service Worker `sync` event (Background Sync API)
     fires even with the app closed.
6. Each queued entry is replayed. The server is idempotent: replays of the
   same `idempotency_key` return `{status: "already_exists"}` with the existing
   row, so nothing duplicates.
7. If the server says `created_possible_duplicate` (meaning another phone
   logged something of the same type within ±2 minutes), the second phone gets
   a prompt: _"looks like Mum's phone logged a feed 47s ago — delete mine?"_.

### Where Android wins

Chrome on Android supports the [Background Sync API], which means writes you
made offline will flush **even if you've closed the app**, as soon as the OS
sees connectivity. This requires the PWA to be **installed** (not just
visited as a tab).

### What iOS does instead

Safari has no Background Sync. The page-level flush triggers
(`visibilitychange`, `online`, the 30 s interval) catch everything **once you
reopen the app**. That's good enough — with a newborn the app gets opened
constantly.

### Limits

- IndexedDB storage may be evicted by the browser after extended inactivity
  (~7 days on iOS, longer on Android). Doesn't matter in practice; the
  trade-off is well-known PWA territory.
- The queue is FIFO. If a single write keeps failing (e.g. the server is
  rejecting it for some bug), later writes wait behind it. Failed writes
  remain in the queue and surface in the badge as `N ↑ (error)`. Open the
  Network tab to diagnose, or see [Troubleshooting](#troubleshooting).

---

## Google Drive backups

The backup container runs nightly at **03:00 local time** (`backup/crontab`).
Without an rclone config it still produces local gzipped snapshots in
`./data/backups/` and prunes them per `RETAIN_LOCAL`. Remote upload requires
a one-time auth dance.

1. **Get a Drive OAuth token on any machine with a browser:**
   ```bash
   rclone authorize "drive"
   ```
   It opens a browser, you sign in, copy the JSON token it prints.

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

- `RETAIN_LOCAL` — local snapshots to keep (default 7).
- `RETAIN_REMOTE_DAYS` — purge remote snapshots older than N days (default 30).

The remote layout is `gdrive:nbio/app-YYYYMMDD-HHMM.db.gz`.

> Tokens refresh themselves as long as `./data/rclone/` is writable from the
> container — which it is in the default compose file.

---

## Restoring from a backup

```bash
docker compose stop app

# from a local snapshot:
docker compose run --rm backup /usr/local/bin/restore.sh /backups/app-YYYYMMDD-HHMM.db.gz

# or pull from Google Drive first:
docker compose run --rm backup /usr/local/bin/restore.sh remote app-YYYYMMDD-HHMM.db.gz

docker compose start app
```

The previous `data/app.db` is renamed to `app.db.broken` (kept for safety;
delete it once you're satisfied).

**Restoring on a fresh machine:** clone the repo, `cp .env.example .env`,
restore an rclone config (if you have it backed up elsewhere — Drive
credentials are not in the snapshot), then run the restore script. The app
will boot against the restored DB.

---

## Reports

`/reports` (or the Reports bottom-nav tab):

- **Today summary** — counts of each event type, time since last of each.
- **24h timeline** — horizontal strip with colour-coded marks per event.
- **7-day heatmap** — events per hour over the last week.
- **Daily totals** — totals per day, last 14 days.

All charts are server-rendered inline SVG: no chart library, no JS bundle.

CSV / paediatrician export is not in v1. If you want it, open an issue — it's
~30 lines.

---

## Troubleshooting

### App doesn't load over Tailscale

- `tailscale status` on the host — is it `online`?
- `docker compose ps` — both services `healthy`?
- `curl -i http://localhost:8000/healthz` on the host — `200 OK`?
- `tailscale ping <host>` from your phone (Tailscale app → ping) — does it
  reach?
- If using Pattern B (`tailscale serve`): `sudo tailscale serve status` shows
  the current routing. Re-run the `tailscale serve` command if it's empty.

### `Install app` option missing on Android

Chrome's install prompt requires:
- The site to be served over `https://` (or `localhost`). Use Tailscale Serve
  (Pattern B) for HTTPS on the tailnet.
- A valid `manifest.webmanifest` and a registered service worker — both are
  present in NBIO.
- You've engaged with the page for ~30 s on this device.

Workaround: **⋮ menu → "Add to Home screen"** still works even when the auto
prompt is absent.

### `Add to Home Screen` missing on iOS Safari

- You must use **Safari**, not Chrome or Firefox on iOS.
- Tap the central Share icon in the bottom toolbar; the option is below the
  share-target row.
- If it still doesn't appear, the page didn't load (check the URL bar).

### Pending badge stuck (writes won't flush)

In the installed PWA:
- Pull-to-refresh to force a foreground flush.
- Check the connection dot — orange means the page thinks you're offline.
  Toggle airplane mode off/on.
- Open DevTools (Chrome remote-debugging from a desktop helps on Android):
  Application → IndexedDB → `nbio.outbox`. Inspect any stuck entry's request
  body and try replaying via the Network tab; the server's response will tell
  you why.

To **drain the queue manually** (loses queued writes):

```js
// in the PWA's DevTools console:
indexedDB.deleteDatabase('nbio')
```

Then reload. New writes will queue cleanly.

### SSE not connecting (header dot stays grey/orange)

- If you've put any reverse proxy between you and the app, response buffering
  will kill SSE. The app already sends `X-Accel-Buffering: no` (nginx) but
  some proxies also need `proxy_buffering off` configured. `tailscale serve`
  is transparent and fine.
- `curl -N http://localhost:8000/api/stream` on the host should show a
  keepalive `: ping` every 20 s and event messages as they happen.

### Two phones showing different events

- Confirm both phones are pointing at the same URL (a stale tab from an
  earlier address won't be receiving SSE).
- Force-refresh both. SSE replay via `Last-Event-ID` is capped at 500 events;
  if a phone has been offline longer than that the page does a full re-fetch
  via `GET /api/events` on reconnect.

### Two phones showing the same event twice (no dup prompt)

- The ±2 min duplicate window only triggers for events of the **same type**
  with `occurred_at` within ±120 s. If both parents logged a feed at exactly
  the same moment, that's the intended dedup target — if it didn't fire,
  check that both `created_by_device` values are different (same device =
  treated as the same writer, no prompt).
- Worst case, swipe-delete one — the soft-delete undo toast gives you a 5 s
  safety net.

### Backup not uploading to Drive

```bash
docker compose exec backup /usr/local/bin/backup.sh
docker compose logs --tail=50 backup
```

Common causes:
- No `rclone.conf` yet — the script will say
  `no rclone config at /config/rclone.conf; skipping remote upload (local snapshot kept)`.
  Run the auth dance in [Backups](#google-drive-backups).
- Token expired — re-run `rclone authorize "drive"` and update the config.
- Drive quota exhausted — extremely unlikely (snapshots are tiny) but check
  the Drive UI.

### Forgot which colour I picked / want to rename my phone

In the installed PWA → DevTools → Application → Local Storage → remove
`nbio.device_color` and `nbio.device_name` → reload. The onboarding modal
reappears.

### Database is locked / `SQLITE_BUSY`

Should not happen with WAL + `busy_timeout=5000` and two writers. If it does:
- Confirm `./data/app.db` is on a **local filesystem**, not NFS/SMB. SQLite
  locking is unreliable over network filesystems. Move the data directory to
  local storage and restart.
- Check if a manual `sqlite3 data/app.db` shell is open and holding a
  transaction — close it.

---

## Development notes

- Local dev without Docker:
  ```bash
  cd app
  pip install -e .[dev]
  DB_PATH=/tmp/nbio.db TZ=Europe/London \
    uvicorn nbio.main:app --reload --host 0.0.0.0 --port 8000
  ```
- The schema is created on first boot from `app/nbio/db.py`. No migrations
  framework in v1 — additive changes are safe; destructive changes need a
  manual `ALTER`.
- **Tests**: full suite at `app/tests/` — `cd app && TZ=UTC python -m pytest`.
  Coverage gate is **90%+** (current: 100%). See
  [`CONTRIBUTING.md`](CONTRIBUTING.md) for the TDD policy and the layout.
- **CI**: GitHub Actions runs lint (ruff), type (mypy), test (pytest
  matrix 3.12 + 3.13), shell (shellcheck + setup.sh dry-run), js
  (`node --check`), and docker (buildx amd64 + compose config) on every
  PR and push. The arm64 cross-build is gated to `workflow_dispatch`
  and tag pushes.

---

## How it works (internals)

- **FastAPI + SQLite (WAL) + Jinja2** in one container. No JS build step;
  static assets are served straight from `app/nbio/static/`.
- **Idempotency**: every client submit carries a UUID `idempotency_key`;
  unique-indexed on the server. Replays silently return the existing row.
- **Cross-parent duplicate prompt**: after inserting an event, the server
  looks for any other non-deleted event of the same type within ±120 s and,
  if found, returns `created_possible_duplicate` so the client can prompt.
- **Live sync** via Server-Sent Events on `/api/stream`. Reconnects use
  `Last-Event-ID` to replay missed events (capped at 500 rows; a larger gap
  triggers a full `GET /api/events?since=…` refetch).
- **Backup**: `sqlite3 .backup` produces a consistent copy with writers still
  online. The backup container mounts `./data` read-only and writes snapshots
  to a separate `./data/backups/` bind.

---

## License

See [`LICENSE`](LICENSE).

[Background Sync API]: https://developer.mozilla.org/en-US/docs/Web/API/Background_Synchronization_API
