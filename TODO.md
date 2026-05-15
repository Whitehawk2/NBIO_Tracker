# TODO

Roadmap for NBIO Tracker, in descending order of priority.

Each item is also tracked as a GitHub issue (linked below) — close the issue
when done, and tick the item here. The two views are kept in sync manually.

## 1. Verify and merge PR #2 (UX phase 1) — [#3](https://github.com/Whitehawk2/NBIO_Tracker/issues/3)

Manual desktop-Chrome verification of the three UX fixes in
**[PR #2](https://github.com/Whitehawk2/NBIO_Tracker/pull/2)**:

- Glanceable last-2-3-days view: today_card with last-of-each, the new
  "Last 3 days" mini-table, and day-grouped event list with sticky headers.
- Single-click custom datetime: always-visible `<input type="datetime-local">`
  pre-filled to "now", `showPicker()` on click, unambiguous "Mon 15 May, 02:47"
  readout above the chips.
- Larger reports: HTML hour-axis labels, CSS-grid heatmap, bigger totals table.

If acceptable: merge PR #2 into `claude/newborn-tracker-app-PoMGY` so it
rolls into the standing **[PR #1](https://github.com/Whitehawk2/NBIO_Tracker/pull/1)**
to `master`.

## 2. Quick server startup script + faster backup setup — [#4](https://github.com/Whitehawk2/NBIO_Tracker/issues/4)

Backup setup currently requires a manual `rclone authorize` then
`rclone config create gdrive drive ...` two-step (see
[README → Google Drive backups](README.md#google-drive-backups)). Make
this scriptable and less of a hassle.

Goals:
- A single entry point — `./setup.sh` (or `make setup`) — that prompts
  for the bare minimum (TZ, BABY_NAME, optional rclone token blob),
  writes `.env`, and brings the stack up.
- Idempotent: re-running it doesn't clobber existing config; missing
  pieces are filled in.
- Designed to work as a stepping stone toward a future k8s deployment:
  keep secrets out of the image, make the bootstrap a single artifact
  that can later be a `Secret` / `ConfigMap`, avoid baked-in state in
  the container image.
- Script header should note Nix users should ignore this and use
  `nix profile install nixpkgs#nbio` / the NixOS module from item 5.

Suggested shape: a tiny bash script + a `Makefile` thin wrapper. No new
runtime deps.

## 3. Tailscale defaults + one-shot `tailscale serve` — [#5](https://github.com/Whitehawk2/NBIO_Tracker/issues/5)

- `docker-compose.yml`: bind to `127.0.0.1:8000:8000` by default
  (Tailscale-only; no LAN exposure). Document the override for users
  who want LAN access.
- The setup script from item 2 should optionally run
  `tailscale serve --bg https://localhost:8000` so the app gets HTTPS
  via MagicDNS in one step.
- Hostname source priority: env var (e.g. `NBIO_TS_HOSTNAME`) → script
  prompt → autodetect from `tailscale status --json | jq .Self.DNSName`.
  Env wins.
- Skip the serve step cleanly when Tailscale isn't installed (just
  print "Tailscale not detected; skipping HTTPS setup").

## 4. Runtime-changeable settings — [#6](https://github.com/Whitehawk2/NBIO_Tracker/issues/6)

Move things that currently live in env vars or first-launch onboarding
onto a settings page editable from the running app:

- Baby name + DOB (currently env `BABY_NAME` only at boot, baked into
  `babies` row at first start).
- Per-device name + colour (currently localStorage; allow re-edit).
- Future: timezone override, retention days, theme (see item 6).

Schema: extend `babies` and `devices`; add a small `settings` table for
truly global toggles. UI: minimal `/settings` page with HTMX form posts
to a new `routes/settings.py`. Reuse existing `repo.upsert_device`
where possible.

## 5. Nix flake: dev shell + installable package — [#7](https://github.com/Whitehawk2/NBIO_Tracker/issues/7)

Two-pronged: dev shell **and** an installable binary suitable for
`nix profile install nixpkgs#nbio`. Nix users are assumed advanced and
will skip the setup script entirely.

Targets:
- **`devShells.default`** for contributors — Python 3.12, uvicorn,
  sqlite, rclone, node (for `node --check` of `app.js`):
  ```bash
  nix develop
  ```
- **`packages.default` / `packages.nbio`** — wraps the FastAPI app
  behind a launcher script so:
  ```bash
  nix profile install github:whitehawk2/nbio_tracker
  nbio          # uvicorn against ~/.local/share/nbio/app.db (or $NBIO_DATA_DIR)
  ```
  Effectively replaces the Docker container for Nix users.
- **`nixosModules.default`** exposing `services.nbio.enable = true`
  with options for port, data dir, timezone, baby name, and the
  backup sidecar's rclone remote / retention. Lives alongside the
  package so one flake input gives both the binary and the systemd
  service.

Stretch: a container image built with `dockerTools.buildLayeredImage`
for an image-build path that's reproducible without `apt-get` —
tangentially helpful for the k8s scenario in item 2.

The setup script from item 2 will print a header comment pointing Nix
users here so the two paths stay clearly separated.

## 6. Two additional Catppuccin themes — [#8](https://github.com/Whitehawk2/NBIO_Tracker/issues/8)

(Blocked on item 4 — needs the settings UI to host the picker.)

Add palettes alongside the current "warm" theme. Recommended starting
pair from the Catppuccin family:

- **Catppuccin Latte** (light)
- **Catppuccin Mocha** (dark)

Wiring:
- Refactor the design tokens at the top of `app/nbio/static/app.css`
  into a `[data-theme="<name>"]` selector pattern (currently `:root`
  + `html.dark`).
- Add a theme picker to the settings UI from item 4.
- Persist the choice per-device in `localStorage` and apply on the
  bootstrap script in `base.html` to avoid a flash of wrong theme.
- Keep the current "warm" palette as the default.
