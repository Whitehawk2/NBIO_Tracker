# TODO

Roadmap for NBIO Tracker, in descending order of priority.

## 1. Verify and merge PR #2 (UX phase 1)

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

## 2. Quick server startup script + faster backup setup

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

Suggested shape: a tiny bash script + a `Makefile` thin wrapper. No new
runtime deps.

## 3. Tailscale defaults + one-shot `tailscale serve`

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

## 4. Runtime-changeable settings

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

## 5. Nix + flake support

Add a `flake.nix` (with a `shell.nix` shim for non-flake users) covering:

- A dev shell with the right Python (3.12), uvicorn, sqlite, rclone.
- A `packages.nbio` derivation buildable via `nix build`.
- A NixOS module exposing `services.nbio.enable = true` so it can be
  deployed onto NixOS hosts without Docker.

Stretch: a container image built with `dockerTools.buildLayeredImage`
for an image-build path that's reproducible without `apt-get` —
tangentially helpful for the k8s scenario in item 2.

## 6. Two additional Catppuccin themes

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
