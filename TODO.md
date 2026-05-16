# TODO

Roadmap for NBIO Tracker, in descending order of priority.

Each item is also tracked as a GitHub issue (linked below) — close the issue
when done, and tick the item here. The two views are kept in sync manually.

## 1. ✅ Verify and merge PR #2 (UX phase 1) — [#3](https://github.com/Whitehawk2/NBIO_Tracker/issues/3)

**Status:** Done — merged and verified on the Pi server (2026-05-16).

Manual desktop-Chrome verification of the three UX fixes in
**[PR #2](https://github.com/Whitehawk2/NBIO_Tracker/pull/2)**:

- Glanceable last-2-3-days view: today_card with last-of-each, the new
  "Last 3 days" mini-table, and day-grouped event list with sticky headers.
- Single-click custom datetime: always-visible `<input type="datetime-local">`
  pre-filled to "now", `showPicker()` on click, unambiguous "Mon 15 May, 02:47"
  readout above the chips.
- Larger reports: HTML hour-axis labels, CSS-grid heatmap, bigger totals table.

## 2. ✅ Quick server startup script + faster backup setup — [#4](https://github.com/Whitehawk2/NBIO_Tracker/issues/4)

**Status:** Done — `setup.sh` + `remove.sh` + `Makefile` merged via
[PR #9](https://github.com/Whitehawk2/NBIO_Tracker/pull/9); tested
end-to-end on the Pi server (2026-05-16).

Backup setup previously required a manual `rclone authorize` then
`rclone config create gdrive drive ...` two-step. Now collapsed into one
prompt inside `./setup.sh`; `./remove.sh` provides a safe symmetric uninstall.

## 3. ✅ Tailscale defaults + one-shot `tailscale serve` — [#5](https://github.com/Whitehawk2/NBIO_Tracker/issues/5)

**Status:** Done — merged via
[PR #10](https://github.com/Whitehawk2/NBIO_Tracker/pull/10); verified
on the Pi server (2026-05-16).

- `docker-compose.yml` binds to `${APP_BIND:-127.0.0.1}:${APP_PORT:-8000}:8000`
  by default (Tailscale-only). LAN exposure is opt-in via `APP_BIND=0.0.0.0`.
- `setup.sh` auto-registers `tailscale serve --bg --https=443
  http://localhost:${APP_PORT}` when Tailscale is detected; `remove.sh`
  clears the registration symmetrically. Both probe with/without sudo and
  skip cleanly when Tailscale isn't installed.
- Hostname source: `NBIO_TS_HOSTNAME` env → prompt → autodetect from
  `tailscale status --json`.

## 4. Nicer UI/UX hints for hidden affordances — [#11](https://github.com/Whitehawk2/NBIO_Tracker/issues/11)

Several gestures in the app are undiscoverable without being told —
swipe-left to delete, tap-to-edit on rows, long-press on a tile for
skip-modal quick-log. Reported from the Pi: "it isn't clear you can
delete an entry by swiping, and there's no button."

Plan: keep every existing gesture (they're 3am-good), but add discoverable
fallbacks and one-time inline hints:
- Per-row `⋯` menu (Edit / Delete) at the trailing edge.
- One-shot inline hint under the first row on first launch.
- Tile long-press caption visible for the first ~3 sessions.
- `aria-label` + tap-to-toggle popover on the header sync dot.
- Warmer empty-state copy: "Tap a tile above to log your first entry."
- "Reset onboarding hints" button (lands once item 8 / #6 brings settings UI).

Acceptance: every primary gesture is discoverable in a fresh install's
first session; dismissed hints stay gone per-device.

## 5. Clearer Tailscale troubleshooting — [#12](https://github.com/Whitehawk2/NBIO_Tracker/issues/12)

Follow-up to item 3 (#5). The new `setup.sh` Tailscale path is opaque
when it goes wrong: the user can't see _what_ command was run, and
doesn't know how to stop the serve without `./remove.sh`.

Plan:
- Script transparency: echo the exact `tailscale serve` command before
  invoking it; add `--verbose` / `NBIO_VERBOSE=1` that `set -x`s the
  Tailscale + rclone blocks; on failure, surface stderr + three recovery
  commands (`status` / re-try / `reset`).
- README "Tailscale troubleshooting" subsection: MagicDNS / HTTPS Certs
  toggles, common-errors table, inspect / partial-remove / full-reset
  commands, `journalctl -u tailscaled -f`, sudo / NOPASSWD notes.

Acceptance: a failed Tailscale setup tells you what failed, why, and the
three commands to recover — without leaving the script output.

## 6. Validate setup + networking docs — [#13](https://github.com/Whitehawk2/NBIO_Tracker/issues/13)

Documentation has accreted across PRs #1, #9, #10 without an end-to-end
re-read. Two specific failure modes:
- The Tailscale path is over-represented; users who **don't** want
  Tailscale can't easily find the "just expose on the LAN" answer.
- Some commands may have drifted out of date.

Plan:
- Fresh-clone audit pass on the Pi. Note every drifted command and
  cross-reference.
- Restructure networking into three equal-weight patterns —
  Local-only / LAN-only / Tailscale — with a comparison table and a
  copy-paste verify snippet at the end of each.
- Top-of-README decision tree pointing at the right pattern in two lines.
- LAN-only section carries an explicit no-auth warning.
- Glossary on first use (tailnet, MagicDNS, PWA, SSE, IDB outbox).
- Architecture diagram becomes deployment-pattern-agnostic.

Acceptance: every command in the README runs cleanly against current
`master`; a non-Tailscale reader can pick a path and reach the app within
30 seconds.

## 7. ✅ Tests + GitHub Actions CI/CD — [#14](https://github.com/Whitehawk2/NBIO_Tracker/issues/14)

**Status:** Done (TDD policy now live).

- 212 tests under `app/tests/` (unit / api / integration / shell).
- **100% line + branch coverage** on `app/nbio/`; CI gate at `--cov-fail-under=90`.
- `.github/workflows/ci.yml`: six jobs (lint / type / test (matrix 3.12+3.13)
  / shell / js / docker), plus `arm64` gated to `workflow_dispatch` + tag pushes.
- `.github/dependabot.yml`: weekly updates for pip / github-actions / docker.
- `CONTRIBUTING.md`: dev setup + TDD policy + the sharp edges to know.

From here on, every PR adds a failing test before the implementation; the
90% gate enforces it.

## 8. ✅ In-place upgrade flow — [#20](https://github.com/Whitehawk2/NBIO_Tracker/issues/20)

**Status:** Done — merged via [PR #22](https://github.com/Whitehawk2/NBIO_Tracker/pull/22).

- `./upgrade.sh`: tag-aware (default = latest annotated tag), `--ref` /
  `--rollback` / `--yes` / `--pull` / `--resolve-only` / `--help`.
- Pre-flight → fetch → resolve → changelog + `.env.example` diff →
  confirm → backup via sidecar → record prev SHA → checkout → build →
  up → `/healthz` poll. Healthz failure halts; rollback is operator-
  initiated by design.
- README "Upgrading" is dual-track (primary script path + self-
  contained manual sequence including a hand-rolled rollback).
- 21 new shell tests under `app/tests/shell/test_upgrade_*.py`; all
  gated `@requires_docker` for the CI test job.
- First PR under the live TDD rule — visible in the commit graph:
  failing tests → implementation → docs.

GHCR pre-built images filed as a follow-up; will land when release
cadence motivates faster Pi upgrades.

## 9. ✅ PWA service worker doesn't pick up upgrades — [#23](https://github.com/Whitehawk2/NBIO_Tracker/issues/23)

**Status:** Fixed (PR pending merge).

- New `nbio.version.static_assets_hash()` — sha256 of every file under
  `nbio/static/`, truncated to 12 hex chars. Path-and-content sensitive,
  insertion-order independent. Cheap (computed per request).
- New `routes/sw.py` route owns `/static/sw.js` and substitutes
  `__NBIO_VERSION__` in the source with the hash before responding;
  `Cache-Control: no-cache` so browsers always revalidate the SW.
- `sw.js` source now declares `CACHE = "nbio-__NBIO_VERSION__"`. The
  existing `activate` handler already purges non-matching caches, so
  a content change → new hash → new cache name → purge → fresh shell.
- New `/api/version` endpoint for diagnostics (returns the hash).
- `app.js` now registers the SW (moved from `base.html`) and listens
  for `updatefound` → `statechange = activated` → shows an
  "Update available · Reload" sticky toast. Differentiated from
  first-install by checking `navigator.serviceWorker.controller`
  was truthy at registration time.
- README "Upgrading" rewritten — was a "known limitation, here's the
  manual reload" caveat; is now "auto-updates, here's the fallback if
  something gets stuck". `upgrade.sh`'s static-asset warning softened
  from `warn:` to `info:` and tells the operator to expect the toast.
- 13 new tests (Python only — JS is `node --check` and Pi manual);
  full suite 261 / 100% coverage.

## 10. ✅ Test-quality pass (close 5 critical gaps from the post-#14 review) — [#21](https://github.com/Whitehawk2/NBIO_Tracker/issues/21)

**Status:** Done — merged via [PR #24](https://github.com/Whitehawk2/NBIO_Tracker/pull/24).

- All 5 critical gaps closed: pages-edge body assertions, page-render
  body inspection, BEGIN IMMEDIATE serialization demonstrated via same-
  row PATCH contention, schema-invariant tests pinning `ux_events_idem`,
  `Last-Event-ID: "0"` vs `""` vs missing all explicitly pinned.
- Real bug uncovered during the work: `created_at` (3-digit SQLite
  millis) lexically compared GREATER than same-instant `updated_at`
  (6-digit Python micros) because `Z` > `4` at the 7th fractional
  position. Fixed by Python-clocking both columns in `create_event`.
- `daily_totals` refactored to compute its cutoff in Python (was
  SQLite's `date('now', '-N days')` which freezer can't reach).
- `FailingConn` moved to conftest; new `reset_dependency_overrides`
  autouse fixture.
- mutmut workflow added as `workflow_dispatch` — not gated, surfaces
  surviving mutants as a backlog signal for future hardening.
- 248 tests, 100% coverage.

## 11. Triage open Dependabot PRs + tighten grouping policy — [#25](https://github.com/Whitehawk2/NBIO_Tracker/issues/25)

Three open Dependabot PRs from the first weekly run of the schedule
set up in #14. Recommendations per-PR plus a meta-fix:

- **[#17](https://github.com/Whitehawk2/NBIO_Tracker/pull/17)** (alpine
  3.20 → 3.23 in /backup): **merge after CI green**. Low-risk point
  bump for the backup sidecar.
- **[#19](https://github.com/Whitehawk2/NBIO_Tracker/pull/19)** (python
  3.12-slim → 3.14-slim in /app): **close as-is**. Skips 3.13 entirely
  and our CI matrix is `3.12 + 3.13`. Replace with a narrower bump to
  3.13-slim now, then add 3.14 to the CI matrix as a follow-up before
  ever bumping the runtime to 3.14.
- **[#18](https://github.com/Whitehawk2/NBIO_Tracker/pull/18)** (actions
  group, 6 updates): **close, split into per-action PRs**. The group
  bundles 2 major-version jumps (`upload-artifact@v4→v7`,
  `checkout@v4→v6`) with 4 routine bumps — if CI fails, you can't tell
  which one broke.

Meta-fix: tighten `.github/dependabot.yml` so the actions group
includes only `patch` + `minor` updates; majors land as individual PRs
with their own CI signal.

Order: dependabot.yml grouping tweak first → close #18 #19 → wait for
next Dependabot run → merge per-action splits → merge #17 → file a
"3.14 to CI matrix" follow-up.

## 12. Runtime-changeable settings — [#6](https://github.com/Whitehawk2/NBIO_Tracker/issues/6)

Move things that currently live in env vars or first-launch onboarding
onto a settings page editable from the running app:

- Baby name + DOB (currently env `BABY_NAME` only at boot, baked into
  `babies` row at first start).
- Per-device name + colour (currently localStorage; allow re-edit).
- Future: timezone override, retention days, theme (see item 14).

Schema: extend `babies` and `devices`; add a small `settings` table for
truly global toggles. UI: minimal `/settings` page with HTMX form posts
to a new `routes/settings.py`. Reuse existing `repo.upsert_device`
where possible.

## 13. Nix flake: dev shell + installable package — [#7](https://github.com/Whitehawk2/NBIO_Tracker/issues/7)

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

## 14. Two additional Catppuccin themes — [#8](https://github.com/Whitehawk2/NBIO_Tracker/issues/8)

(Blocked on item 12 — needs the settings UI to host the picker.)

Add palettes alongside the current "warm" theme. Recommended starting
pair from the Catppuccin family:

- **Catppuccin Latte** (light)
- **Catppuccin Mocha** (dark)

Wiring:
- Refactor the design tokens at the top of `app/nbio/static/app.css`
  into a `[data-theme="<name>"]` selector pattern (currently `:root`
  + `html.dark`).
- Add a theme picker to the settings UI from item 8.
- Persist the choice per-device in `localStorage` and apply on the
  bootstrap script in `base.html` to avoid a flash of wrong theme.
- Keep the current "warm" palette as the default.
