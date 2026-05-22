# CLAUDE.md

Project context for Claude sessions working in this repo. The README is
the operations manual; this file is the cheat-sheet for getting useful
work done without re-exploring from scratch.

## Project at a glance

**NBIO Tracker** — a two-parent newborn input/output (feed / wee / poo)
logger. Self-hosted on a home server, accessed over Tailscale, designed
for **3am ergonomics**: big tap tiles, retro-time chip picker, smart
defaults, auto dark mode at night, haptic feedback, offline-capable PWA.

Two-parent live sync is the headline feature; nightly Google Drive
backup is the disaster-recovery story.

**Primary client: Android Chrome PWA.** iOS is supported but
secondary — both parents are on Android in production. When
debugging client-side behaviour, verify on Android first; an
iOS-only theory that doesn't reproduce on Android is the wrong
theory.

## Stack

- **Backend**: FastAPI + plain `sqlite3` (no ORM) + Jinja2/HTMX,
  Python 3.12+.
- **Frontend**: vanilla-JS PWA with an IndexedDB outbox + service worker.
- **Live sync**: in-process SSE broker, `Last-Event-ID` replay (capped 500).
- **Backup**: alpine + sqlite + rclone + busybox cron sidecar.
- **Two containers**: `app` (FastAPI) + `backup` (sidecar). `data/`
  bind-mounted from the host.

## Layout

```
app/
  Dockerfile                fastapi + uvicorn image
  pyproject.toml            python deps, tool config
  nbio/
    config.py               pydantic-settings; reads .env
    db.py                   connect() + init_db() + PRAGMAs
    models.py               Pydantic request/response shapes
    repo.py                 ALL SQL lives here — 16 functions
    sse.py                  in-process asyncio broker (singleton)
    main.py                 FastAPI app, lifespan, static mount
    routes/
      health.py             /healthz
      pages.py              /, /reports + Jinja helpers
      events.py             /api/events*  (CRUD, undelete, last-side)
      devices.py            /api/devices* (upsert, list)
      stream.py             /api/stream   (SSE)
    templates/              base.html + partials/
    static/                 app.js, sw.js, idb.js, app.css, manifest, icons/
  tests/                    (lands with #14)

backup/
  Dockerfile, crontab, backup.sh, restore.sh

setup.sh                    one-shot bootstrap (handles rclone + tailscale)
upgrade.sh                  tag-aware in-place upgrade; --rollback symmetric
remove.sh                   safe uninstall
Makefile                    setup / up / down / logs / backup / upgrade / rollback / ...
docker-compose.yml
.env.example                config knobs (incl. APP_BIND default 127.0.0.1)
data/                       gitignored bind mount (app.db + backups + rclone.conf +
                            .upgrade-prev-ref)
README.md                   full operations guide
TODO.md                     live roadmap, linked to GitHub issues
```

## Architecture invariants

- **One DB connection per request** via `Depends(get_conn)`. Never share
  connections across coroutines.
- **All SQL lives in `repo.py`**. Routes are thin wrappers — no inline SQL,
  no ad-hoc cursors. New SQL goes here too.
- **ISO-8601 UTC** in the DB. Local TZ only for display, computed at
  render time from `settings.tz`.
- **Soft delete** via `deleted_at`. `id` survives undelete so SSE clients
  converge. 5s undo toast on the client.
- **Idempotency key** is `UNIQUE` on `events`. Writes use `BEGIN
  IMMEDIATE`; an `IntegrityError` collision triggers a `fetch_event_by_idem`
  and returns `status="already_exists"`. No 4xx on retry.
- **Cross-parent dup detection**: ±2-min window query after insert.
  Server inserts anyway (accept-by-default), client decides whether to
  prompt the user.
- **SSE replay cap = 500**. Clients fall back to `GET /api/events?since=`
  if their gap is larger.

## Sharp edges (the ones that will trip you up)

- **`sse.broker` is a module-level singleton imported by reference** in
  `routes/{events,devices,stream}.py`. Tests must **mutate state**
  (`broker._subs.clear()`), **not** replace the instance — rebinding
  `nbio.sse.broker` won't update the already-imported names. (Future:
  move to `app.state`. Issue TBD.)
- **SQLite must live on a local FS** (ext4/btrfs). Never NFS / SMB.
- **iOS PWA has no Background Sync**. Outbox flush relies on
  `visibilitychange` + page-foreground + a 30s belt-and-braces interval.
- **Service worker cache name is templated at response time** by
  `routes/sw.py`: `__NBIO_VERSION__` in `sw.js` is replaced with a
  content hash of everything under `nbio/static/`. The route owns
  `/static/sw.js` and MUST be included before the `app.mount("/static",
  ...)` line in `main.py` — otherwise the StaticFiles mount serves the
  raw placeholder. Hash source: `nbio.version.static_assets_hash()`
  (filed under #23). Also exposed at `/api/version` for diagnostics.
- **`APP_BIND=127.0.0.1` by default** — Tailscale serve is the only
  external path in. LAN exposure is opt-in via `APP_BIND=0.0.0.0`.
- **No auth** — the tailnet is the perimeter. `tailscale funnel` is
  deliberately excluded from the threat model.
- **`data/rclone/` mount is rw**, not ro — rclone refreshes its OAuth
  token in place.
- **TestClient is single-threaded** — for real concurrency tests use
  `httpx.AsyncClient(transport=ASGITransport(app))` + `asyncio.gather`,
  and a file-backed DB so WAL actually engages.

## Conventions

- **TDD** (live): failing test before the implementation, same PR.
  Coverage cannot dip below 90% (currently 100%); CI gates via
  `--cov-fail-under=90`. See `CONTRIBUTING.md`.
- **Branches**: `claude/<slug>`; base on `master`.
- **Commits**: new commits, never `--amend`. Never `--no-verify`. Never
  skip signing.
- **Pull requests**: when work on a feature branch is pushed and
  green, **open the PR immediately** — don't wait to be asked.
  Use `mcp__github__create_pull_request` (no `gh` CLI in this
  environment). Title `<type>: <one-line summary>`; body with
  Summary + Test plan sections matching the format under "Creating
  pull requests" at the top of this prompt. Skip only if the user
  explicitly says "don't open a PR" or the change is a tiny
  docs-only touch they've said they'll merge directly.
- **Shell**: `#!/usr/bin/env bash` + `set -euo pipefail`. Probe for
  required tools before running them. `shellcheck --severity=warning`
  clean.
- **SQL**: parameterised always; never f-strings.
- **Test dates**: use dynamic values (`datetime.now(UTC)`,
  `freezer.move_to(...)`) **whenever a test assertion depends on
  date proximity** — "last 3 days" filters, freezer comparisons,
  `created_at`/`updated_at` ordering, relative-time strings. Hardcoded
  date literals are fine for arbitrary fixture data (the row just
  needs to exist), but a baked-in `"2026-05-16"` that flows into a
  time-windowed assertion is a guaranteed time-delayed flake — see
  [#78](https://github.com/Whitehawk2/NBIO_Tracker/issues/78) for the
  post-v1.1.0 incident that broke 3 tests at once 3 days after they
  were written. **If you hardcode a date in a test, prove it can't
  drift** (or annotate it `# date-fixture-safe`).
- **No new docs files** unless asked. **No emoji** unless asked.
- **No comments that re-state the code**. Comments explain non-obvious
  WHY only.

## Dev quickstart

```bash
pip install -e ./app[dev]
cd app
TZ=UTC python -m pytest                   # full suite (212 tests, ~30s)
TZ=UTC python -m pytest --cov-report=html # drill into coverage misses
ruff check nbio tests
ruff format --check nbio tests
mypy nbio --ignore-missing-imports
```

`TZ=UTC` matters — the timezone-dependent helpers read the process tz.

Stack ops (any time):

```bash
./setup.sh                                # one-shot bootstrap
make logs                                 # tail app logs
make backup                               # force a backup right now
make down                                 # stop stack
make upgrade                              # ./upgrade.sh — latest tag by default
make rollback                             # ./upgrade.sh --rollback
./remove.sh                               # symmetric uninstall
```

## Upgrading

`./upgrade.sh` is tag-aware by default. Resolution priority: explicit
positional tag → `--ref <branch|tag>` → latest annotated tag. Bails on
unknown refs.

Flow: pre-flight (docker / compose / git / clean tree) → fetch origin +
tags → show changelog and `.env.example` diff → confirm → backup
snapshot via the sidecar (refuses to proceed without one; override with
`NBIO_SKIP_BACKUP=1` for dev) → write current SHA to
`data/.upgrade-prev-ref` → checkout target → build → up → poll
`/healthz` for 60s.

**Healthz failure halts, doesn't auto-rollback.** Design choice: the
broken state is left intact so the operator can `docker compose logs
app`, then choose to `./upgrade.sh --rollback` once diagnosed. Don't
mask failures with an automatic revert.

For tests, three contract env vars short-circuit the side-effectful
steps so the shell suite can exercise the script without a real Docker
daemon: `NBIO_SKIP_BACKUP=1`, `NBIO_SKIP_BUILD=1`, `NBIO_SKIP_HEALTHZ=1`.
A stubbed `docker` on PATH gets pre-flight past the version checks. See
`app/tests/shell/test_upgrade_*.py`.

The README has a self-contained "Manual upgrade (without the script)"
section that drives the equivalent sequence with raw `git` + `docker
compose` commands — including a manual `--rollback` using the same
`data/.upgrade-prev-ref` file the script writes. Point users there
when they ask "how do I upgrade without running the script".

## CI surface

`.github/workflows/ci.yml`, six jobs (one gated):

| Job | Trigger | What it does |
|---|---|---|
| `lint` | every PR / push | `ruff check` + `ruff format --check` |
| `type` | every | `mypy app/nbio --ignore-missing-imports` |
| `test` | every, matrix py 3.12 + 3.13 | `pytest --cov --cov-fail-under=90`; `TZ=UTC`; uploads `coverage.xml` + `htmlcov/` as artifacts |
| `shell` | every | `shellcheck --severity=warning` + `bash -n` + `setup.sh --dry-run` in a tmpdir |
| `js` | every | `node --check` on every `static/*.js` |
| `docker` | every | buildx amd64 for both images + import smoke + `docker compose config -q` |
| `arm64` | `workflow_dispatch` + tag pushes | QEMU cross-build for the Pi |

`concurrency: cancel-in-progress` at the workflow level so stacked pushes
to the same ref don't pile up.

## Environment quirks (Claude Code on the web)

- Repo cloned fresh per session; container is ephemeral. Commit + push
  anything worth keeping before the session ends.
- Outbound network is policy-gated; `apt` / `apk` / `pip install` against
  public registries may not work in this sandbox.
- **GitHub access is via `mcp__github__*` tools only**. No `gh` CLI, no
  direct REST. Scope restricted to `whitehawk2/nbio_tracker`.
- **Tag pushes are blocked** by the git proxy (HTTP 403). Branch pushes
  work for the configured `claude/...` pattern. Release tags need the
  user to push them locally or create a GitHub Release via the web UI.
- **Plan mode** restricts edits to the plan file only — no source
  changes, no commits, no non-readonly tools.

### Web Claude debugging: verify, don't guess

Lessons from the v1.1.1 "formula chips not appearing" debug — three
PRs landed before the actual cause was found, because the symptom
was never re-verified between fixes.

- **"PR merged" ≠ "server running new code" ≠ "PWA showing new code".**
  Three independent caches: server build, SW cache, browser HTTP.
  Before proposing a client-side fix to a deployed-PWA bug,
  ALWAYS verify the server is current first. Cheapest check:

      curl http://<dev-host>/api/version

  vs. on a master worktree:

      python -c "from nbio.version import static_assets_hash; print(static_assets_hash())"

  Match → debug client. Mismatch → debug the deploy path first.
- **Dev server uses manual `docker compose build && up -d`, NOT
  `make upgrade` / `upgrade.sh`.** Don't assume the documented
  upgrade flow is the one in use — ask.
- **The SW `updatefound` event is racy against `register()`.**
  When the browser auto-checks the SW source on navigation, the
  install can complete BEFORE a JS-level `updatefound` listener
  attached after `register()` resolves. Hook `controllerchange`
  on `navigator.serviceWorker` instead — it fires when the new
  SW claims the page, with no pre-register race. The "Update
  available · Reload" toast (v1.1.0 → v1.1.1) shipped using
  `updatefound` and never fired once in production for exactly
  this reason.
- **Android Chrome is the primary debug surface.** Both parents
  use Android in production; iOS is supported but secondary. If a
  client-side theory only explains iOS, it's the wrong theory for
  the bug you're chasing — go back and find the Android-reproducible
  cause first.
- **Inside a service worker, `fetch(req)` uses the browser HTTP
  cache by default.** "Network-first" SW logic without
  `fetch(req, { cache: "reload" })` is a lie on Android Chrome —
  `/static/*` has no `Cache-Control` from FastAPI's StaticFiles
  mount, Chrome heuristically caches for hours, and the SW returns
  yesterday's bytes thinking it went to the network. Always pass
  `cache: "reload"` for network-first asset fetches.
- **iOS PWAs cache more aggressively still.** Beyond the SW HTTP
  cache, the SW source itself can be cached for 24h despite
  `Cache-Control: no-cache`; pass `updateViaCache: "none"` to
  `register()`. And HTML-baked
  `window.NBIO_CONFIG.version` compared to `/api/version` at boot,
  with a `sessionStorage`-gated reload on mismatch, is the
  safety net. Key the sessionStorage flag on the target server
  hash (`nbio.sw_reloaded.<hash>`) — iOS standalone PWA sessions
  survive for weeks, and an unkeyed flag permanently disarms the
  self-heal after any single prior reload.
- **Don't ship multiple speculative fixes in series.** Each one
  costs trust. Verify the symptom resolves between fixes — and
  if the user reports "still broken", treat their next message
  as the start of the debug, not "ship another guess".
- **`/recover` is the stuck-PWA escape hatch.** Self-contained
  route (no `/static/*` deps, `Cache-Control: no-store`) that
  unregisters every SW + clears Cache Storage, deliberately
  leaving IndexedDB intact so the outbox of unsynced events
  survives. Point users there when the normal SW lifecycle
  isn't dislodging a wedged client and the alternative would be
  "clear app data" (destroys the outbox). README has the user-
  facing doc under "PWA stuck on an older version after a deploy".

## Issue / roadmap

`TODO.md` is the source of truth. Every item links to a GitHub issue;
tick the checkbox and close the issue together when done. Don't reorder
without checking with the user first. Current top of stack: #14 (tests +
CI), then #11 (UX hints), #12 (Tailscale troubleshooting), #13 (docs
audit), #6 (runtime settings), #7 (Nix), #8 (themes).

## Pointers

- `README.md` — full operations guide (setup, networking, PWA install,
  offline queue, backup/restore, troubleshooting).
- `TODO.md` — roadmap.
- `CONTRIBUTING.md` — TDD policy + dev setup.
- `/reports/print?days={7|14|30}` — pediatrician-handoff report
  (issue #56). Self-contained A4-portrait HTML, reuses
  `_weight_history_context` / `_timeline_marks` / `_day_formula_cc`
  from `routes/pages.py`. Same self-contained discipline as
  `/recover`: no `/static/*` refs so a stuck SW can't poison it.
