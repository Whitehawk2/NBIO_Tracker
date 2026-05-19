# TODO

Roadmap for NBIO Tracker, in descending order of priority.

Each item is also tracked as a GitHub issue (linked below) — close the issue
when done, and tick the item here. The two views are kept in sync manually.

---

> 🎯 **v1.1.0 shipped (2026-05-18).** v1.2.0 scope is **TBD** — pick from the
> 22 parked candidates below. Tracked in
> [#76](https://github.com/Whitehawk2/NBIO_Tracker/issues/76).
>
> Recommended shortlist: **#54** Sleep tracking + **#63** Vitest JS tests
> + **#65** GHCR pre-built images, optionally adding **#56** Pediatrician PDF.

---

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

## 4. ✅ Production-use findings — first 12 hours — [#28](https://github.com/Whitehawk2/NBIO_Tracker/issues/28)

**Status:** Done — all 5 findings shipped and tested on the Pi.

- **#4** notes vanishing after refresh →
  [PR #35](https://github.com/Whitehawk2/NBIO_Tracker/pull/35) — new
  `GET /api/events/{id}`; modal fetches the canonical row on open
  instead of reading stale row-local data attrs.
- **#3** `./upgrade.sh --ref master` silent exit 1 →
  [PR #36](https://github.com/Whitehawk2/NBIO_Tracker/pull/36) — ERR
  trap + `|| die` on every `git checkout`. Two follow-ups:
  [PR #40](https://github.com/Whitehawk2/NBIO_Tracker/pull/40)
  (`git fetch --tags --force` for conflicting tag SHAs) and
  [PR #41](https://github.com/Whitehawk2/NBIO_Tracker/pull/41)
  (deployed SHA tracked in `data/.upgrade-current-ref` so a manual
  `git pull` no longer fools the "nothing to do" short-circuit).
- **#5** formula vs breastfeeding →
  [PR #37](https://github.com/Whitehawk2/NBIO_Tracker/pull/37) —
  new `formula` event type, `formula_brand` + `formula_volume_ml`
  columns, 4-tile home (🤱 Breast / 🍼 Formula / 💧 Wee / 💩 Poo),
  brand + volume chip modal, migration framework
  (`nbio/migrations/` gated by `PRAGMA user_version`) + SQLite
  12-step rebuild renaming legacy `feed` rows → `breast`.
- **#1** last-3-days bucketing under UTC →
  [PR #38](https://github.com/Whitehawk2/NBIO_Tracker/pull/38) —
  new `nbio/tz.py`; `today_counts` / `daily_totals` shift
  `occurred_at` by the server's current local-tz offset before
  bucketing.
- **#2** reactive overview refresh →
  [PR #39](https://github.com/Whitehawk2/NBIO_Tracker/pull/39) —
  `bumpOverviews()` updates the today-card counters and
  last-3-days mini-table inline on POST and SSE without a reload.
- **Production-test follow-up** →
  [PR #42](https://github.com/Whitehawk2/NBIO_Tracker/pull/42) —
  tile long-press hardened to a 3-second hold that cancels on
  finger movement (no more accidental logs while scrolling);
  formula volume chips wrap responsively (no more cut-off at 150cc).

Suite at 335 tests / 100% line + branch coverage on `master` at the
close of this item.

## 5. ✅ Nicer UI/UX hints for hidden affordances — [#11](https://github.com/Whitehawk2/NBIO_Tracker/issues/11)

**Status:** Done — shipped via [PR #46](https://github.com/Whitehawk2/NBIO_Tracker/pull/46),
with a comprehensive regression-fix follow-up in
[PR #48](https://github.com/Whitehawk2/NBIO_Tracker/pull/48).

[PR #46](https://github.com/Whitehawk2/NBIO_Tracker/pull/46) — the core hints work:
- Per-row `⋯` Edit / Delete action sheet with `aria-label`, hover, cursor.
- One-shot first-row hint above the event list ("Tap to edit · swipe left to delete").
- Per-tile "Hold 3s to log instantly" caption.
- Sync-dot tap-to-explain popover + state-aware aria-labels.
- Empty-state copy nudges users to the tiles.
- `:focus-visible` outlines, dark-mode `--text-muted` contrast bump,
  notes-exists 📝 icon, distinct `.no-recent` tile placeholder.
- Persistence via three `nbio.hint.<name>` localStorage flags
  (`first_row`, `long_press`, `sync_dot`). Future #6 settings UI will
  clear them via prefix filter.

[PR #48](https://github.com/Whitehawk2/NBIO_Tracker/pull/48) — v1.1.0 regression fixes
after Pi-side testing surfaced multiple production issues:
- White / black rectangles on new UI elements (defensive
  `appearance: none` + solid backgrounds; today-card 4-tile dropped in
  favour of a dedicated `today-formula-strip` row).
- `Mater...` truncation on formula rows (event-row grid swapped to
  `max-content` + `minmax(0, 1fr)`).
- Reports timeline marks rendering BLACK (breast/formula classes mapped
  to the existing `.mark-feed` rule) and missing today's poos (TZ bug:
  bucket by local date, not UTC prefix).
- Reactive cc refresh on POST (missing fields in optimistic dict) AND
  on DELETE (double-decrement from `event.deleted` SSE own-echo —
  fixed by an `ownDeletes` Map mirroring the existing `ownIdems`).
- Tile-hint × button unclickable — root cause: `<button>` nested inside
  `<button class='tile'>`. Wrapped each tile + hint in `<div class='tile-wrap'>`.
- Long-notes overlap → inline notes text dropped; 📝 icon remains.
- Per-day cc on each reports timeline strip + tap-to-show-detail
  toast on every timeline mark (Android Chrome doesn't fire SVG
  `<title>` on touch — needs a JS click handler).
- 7-day heatmap caption added so it reads as a pattern tool.

Suite at **411 tests / 100% line + branch coverage** on `nbio/` at the
close of this item. Ready to ship as v1.1.0.

## 6. ✅ Clearer Tailscale troubleshooting — [#12](https://github.com/Whitehawk2/NBIO_Tracker/issues/12)

**Status:** Done — shipped via [PR #50](https://github.com/Whitehawk2/NBIO_Tracker/pull/50).

- `setup.sh` echoes the exact `tailscale serve` command before invoking
  it; new `--verbose` / `NBIO_VERBOSE=1` flag enables `set -x` around
  the Tailscale + rclone blocks; on failure the script surfaces stderr
  plus three recovery commands (`status` / re-try / `reset`).
- README gains a "Tailscale troubleshooting" subsection covering
  MagicDNS / HTTPS Certs toggles, a common-errors table, inspect /
  partial-remove / full-reset commands, `journalctl -u tailscaled -f`,
  and sudo / NOPASSWD notes.

## 7. ✅ Validate setup + networking docs — [#13](https://github.com/Whitehawk2/NBIO_Tracker/issues/13)

**Status:** Done — shipped via [PR #50](https://github.com/Whitehawk2/NBIO_Tracker/pull/50)
(combined with #12 since the two issues overlapped heavily).

- Networking restructured into three equal-weight patterns —
  Local-only / LAN-only / Tailscale — with a comparison table and a
  copy-paste verify snippet at the end of each section.
- Top-of-README decision tree (two lines) pointing at the right pattern.
- LAN-only section carries an explicit no-auth warning.
- Inline glossary on first use (tailnet, MagicDNS, PWA, SSE, IDB outbox).
- Architecture diagram now deployment-pattern-agnostic.
- Fresh-clone command audit done; drifted commands fixed.

## 8. ✅ Tests + GitHub Actions CI/CD — [#14](https://github.com/Whitehawk2/NBIO_Tracker/issues/14)

**Status:** Done (TDD policy now live).

- 212 tests under `app/tests/` (unit / api / integration / shell).
- **100% line + branch coverage** on `app/nbio/`; CI gate at `--cov-fail-under=90`.
- `.github/workflows/ci.yml`: six jobs (lint / type / test (matrix 3.12+3.13)
  / shell / js / docker), plus `arm64` gated to `workflow_dispatch` + tag pushes.
- `.github/dependabot.yml`: weekly updates for pip / github-actions / docker.
- `CONTRIBUTING.md`: dev setup + TDD policy + the sharp edges to know.

From here on, every PR adds a failing test before the implementation; the
90% gate enforces it.

## 9. ✅ In-place upgrade flow — [#20](https://github.com/Whitehawk2/NBIO_Tracker/issues/20)

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

## 10. ✅ PWA service worker doesn't pick up upgrades — [#23](https://github.com/Whitehawk2/NBIO_Tracker/issues/23)

**Status:** Done — merged via [PR #26](https://github.com/Whitehawk2/NBIO_Tracker/pull/26).

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

## 11. ✅ Test-quality pass (close 5 critical gaps from the post-#14 review) — [#21](https://github.com/Whitehawk2/NBIO_Tracker/issues/21)

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

## 12. Triage open Dependabot PRs + tighten grouping policy — [#25](https://github.com/Whitehawk2/NBIO_Tracker/issues/25)

**Status:** Meta-fix shipped; per-action splits parked as accepted risk
until v1.1.0 cycle (2026-05-17).

Progress so far:
- **Meta-fix** — `.github/dependabot.yml` grouping tightened so only
  `patch` + `minor` updates bundle; majors land alone. Merged via
  [PR #29](https://github.com/Whitehawk2/NBIO_Tracker/pull/29).
- **[#17](https://github.com/Whitehawk2/NBIO_Tracker/pull/17)** (alpine
  3.20 → 3.23 in /backup): merged.
- **[#18](https://github.com/Whitehawk2/NBIO_Tracker/pull/18) /
  [#19](https://github.com/Whitehawk2/NBIO_Tracker/pull/19)** —
  superseded by Dependabot's next run; closed.

Carried over (accepted risk, revisit in v1.1.0 cycle):
- **[#30](https://github.com/Whitehawk2/NBIO_Tracker/pull/30)**
  `actions/setup-python` 5→6 — minor; safest to merge first.
- **[#31](https://github.com/Whitehawk2/NBIO_Tracker/pull/31)**
  `docker/setup-buildx-action` 3→4 — major.
- **[#32](https://github.com/Whitehawk2/NBIO_Tracker/pull/32)**
  `actions/upload-artifact` 4→7 — three majors at once; riskiest.
- **[#33](https://github.com/Whitehawk2/NBIO_Tracker/pull/33)**
  `actions/setup-node` 4→6 — two majors.
- **[#34](https://github.com/Whitehawk2/NBIO_Tracker/pull/34)**
  `docker/setup-qemu-action` 3→4 — major.

Also still owed: **"add Python 3.14 to CI matrix"** follow-up before
ever bumping the runtime to 3.14-slim.

## 13. ✅ Runtime-changeable settings — [#6](https://github.com/Whitehawk2/NBIO_Tracker/issues/6)

**Status:** Done — shipped via [PR #51](https://github.com/Whitehawk2/NBIO_Tracker/pull/51)
(plus a horizontal-scroll bottom-nav polish fix landed alongside).

- New `/settings` page reachable from a 3-column bottom nav
  (Home / Reports / Settings) — baby name + DOB editable inline,
  per-device name + colour editable, timezone override, hint reset,
  and an `/api/server-info` panel + JSON/CSV event export.
- Schema migration 002 adds the `app_settings` singleton table
  (`id=1` CHECK enforced, holds `tz` + `notes_md`).
- Header now auto-refreshes the baby age (cron hourly + `visibilitychange`).
- Pre-paint theme bootstrap in `base.html` reads
  `localStorage.nbio.theme` synchronously so picker swaps don't flash.
- Future-auth seam in place: `current_actor` dependency stub +
  `X-Device-Id` header convention, ready for per-actor enforcement
  when the auth feature lands.

## 14. Nix flake: dev shell + installable package — [#7](https://github.com/Whitehawk2/NBIO_Tracker/issues/7)

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

## 15. ✅ Two additional Catppuccin themes — [#8](https://github.com/Whitehawk2/NBIO_Tracker/issues/8)

**Status:** Done — shipped via [PR #52](https://github.com/Whitehawk2/NBIO_Tracker/pull/52)
(bundled with the Vitamin D tracker — see item 16).

- Three theme cards in Settings → Display: **Warm** (default, auto
  light/dark), **Catppuccin Latte** (always light), **Catppuccin
  Mocha** (always dark). Each card carries a 5-swatch palette preview
  (bg / accent / feed / poo / vit D).
- All three palettes share **Catppuccin Lavender** for `--accent`
  (`#7287fd` light, `#b4befe` dark).
- Design tokens refactored under a `[data-theme="<name>"]` selector
  pattern; pre-paint bootstrap in `base.html` applies the choice
  before first render to avoid flashing.
- Warm theme auto-toggles light/dark on `html.dark`; Latte stays light
  past sunset and Mocha stays dark at sunrise, by design.

## 16. ✅ Vitamin D tracking — v1.1.0 deliverable (no prior issue)

**Status:** Done — shipped via [PR #52](https://github.com/Whitehawk2/NBIO_Tracker/pull/52).

Pediatric guidance is one drop of vit D per day. Added a 5th event
type + a once-daily surface so parents have a "did we give it?" answer
at a glance.

- Schema migration 003 widens the events `type` CHECK to include
  `'vitd'`. SQLite 12-step rebuild; existing rows preserved; idempotent.
  `user_version` 2 → 3.
- Models / repo: `EventType` literal, `today_counts['vitd']`,
  `last_event_of_each_type['vitd']`, `daily_totals[*].vitd`,
  `_timeline_marks` + `_mark_tooltip` all aware of the new type.
- UI: **Vit D banner above the tiles** with three states (empty,
  given, late-day). After 18:00 local with no dose yet, the banner
  warms (`color-mix` against `--vitd`) and the label bolds — purely
  CSS-driven, no notifications. JS keeps the banner reactive
  (`wireVitDBanner`, `renderVitdBanner`, `refreshVitdLateClass`,
  `bumpOverviews` vitd branch).
- Reports: 💊 column in the daily-totals table (✓ / —), a 4th legend
  dot, and a `.mark-vitd` class on the timeline (gold fill via the
  per-theme `--vitd` token).
- 110 new tests across the suite (api, repo, models, migration,
  helpers, JS source pins, CSS rule pins). Suite at **578 / 100%**.

---

## Backlog — v1.2.0 candidates (post-v1.1.0 brainstorm + audit)

22 candidates parked as GitHub issues after v1.1.0 shipped. Decision for
v1.2.0 scope tracked in [#76](https://github.com/Whitehawk2/NBIO_Tracker/issues/76).

### Parent-facing features

- 🆕 [#54](https://github.com/Whitehawk2/NBIO_Tracker/issues/54) **P1** ·
  Sleep tracking — 6th event type with start/stop sessions *(M)*.
- 🆕 [#55](https://github.com/Whitehawk2/NBIO_Tracker/issues/55) **P2** ·
  Growth log: weight / length / head-circ with WHO percentile overlay *(M)*.
- 🆕 [#56](https://github.com/Whitehawk2/NBIO_Tracker/issues/56) **P2** ·
  Pediatrician handoff: printable PDF / print-stylesheet report *(S)*.
- 🆕 [#57](https://github.com/Whitehawk2/NBIO_Tracker/issues/57) **P3** ·
  Web Push notifications for late-day vit D nudge *(M)*.
- 🆕 [#58](https://github.com/Whitehawk2/NBIO_Tracker/issues/58) **P3** ·
  Vit D streak counter on the banner *(XS)*.
- 🆕 [#59](https://github.com/Whitehawk2/NBIO_Tracker/issues/59) **P3** ·
  Per-actor history rollup ("who logged what") *(S)*.
- 🆕 [#60](https://github.com/Whitehawk2/NBIO_Tracker/issues/60) **P4** ·
  Twin / multi-baby support — schema spike + feature flag *(L)*.
- 🆕 [#61](https://github.com/Whitehawk2/NBIO_Tracker/issues/61) **P3** ·
  Onboarding wizard — first-launch 3-step flow *(S)*.

### Engineering quality

- 🆕 [#62](https://github.com/Whitehawk2/NBIO_Tracker/issues/62) **P2** ·
  Playwright E2E: happy-path + offline-flush + SSE *(M)*.
- 🆕 [#63](https://github.com/Whitehawk2/NBIO_Tracker/issues/63) **P2** ·
  Vitest JS unit tests: idb.js, helpers, optimistic dict *(S)*.
- 🆕 [#64](https://github.com/Whitehawk2/NBIO_Tracker/issues/64) **P3** ·
  Move `sse.broker` singleton onto `app.state` *(S)*.
- 🆕 [#68](https://github.com/Whitehawk2/NBIO_Tracker/issues/68) **P3** ·
  Accessibility audit — axe-core in CI + screen-reader sweep *(S)*.

### Ops / deployment

- 🆕 [#65](https://github.com/Whitehawk2/NBIO_Tracker/issues/65) **P2** ·
  GHCR pre-built multi-arch images on tag push *(S)*.
- 🆕 [#66](https://github.com/Whitehawk2/NBIO_Tracker/issues/66) **P2** ·
  Backup restore-drill in CI + integrity_check on every write *(S)*.
- 🆕 [#67](https://github.com/Whitehawk2/NBIO_Tracker/issues/67) **P4** ·
  Real auth — passkey-only design spike for opt-in LAN exposure *(L)*.
- 🆕 [#72](https://github.com/Whitehawk2/NBIO_Tracker/issues/72) **P4** ·
  Observability — /metrics Prometheus endpoint + structured logging *(S)*.

### UX polish

- 🆕 [#70](https://github.com/Whitehawk2/NBIO_Tracker/issues/70) **P2** ·
  Feed-side balance + interval-since-last on today card *(S)*.
- 🆕 [#71](https://github.com/Whitehawk2/NBIO_Tracker/issues/71) **P4** ·
  Tunable settings — late-vit-D hour, dup-window, undo-toast *(XS)*.
- 🆕 [#73](https://github.com/Whitehawk2/NBIO_Tracker/issues/73) **P3** ·
  Mobile keyboard polish — inputmode + iOS safe-area *(XS)*.

### Data / reports

- 🆕 [#69](https://github.com/Whitehawk2/NBIO_Tracker/issues/69) **P3** ·
  Long-range trends report (>14 days, up to all-time) *(S)*.

### Audit-derived (post-v1.1.0 cleanup)

- 🆕 [#74](https://github.com/Whitehawk2/NBIO_Tracker/issues/74) **P4** ·
  Migration: partial index for vit D last-event queries *(XS)*.
- 🆕 [#75](https://github.com/Whitehawk2/NBIO_Tracker/issues/75) **P5** ·
  WHY comments on race-condition mitigations in app.js *(XS)*.

### Recommended v1.2.0 shortlist

One big-ticket feature + one quality investment + one ops win:

- 🎯 **#54** — Sleep tracking
- 🛡️ **#63** — Vitest unit tests *(defer #62 Playwright until JS stabilises)*
- 🚀 **#65** — GHCR pre-built images

Optional widen: **#56** — Pediatrician PDF *(slots cheaply alongside sleep
tracking since both touch reports)*.

Decision criteria captured in [#76](https://github.com/Whitehawk2/NBIO_Tracker/issues/76).
