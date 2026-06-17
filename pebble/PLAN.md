# NBIO Companion for Pebble Time 2 — Design Plan

> **Status:** revised after pre-code design review. Awaiting spike to
> answer Q1–Q6 (§9). If the spike passes, the spike code IS Phase 1.

## Revision log

This is the second iteration. The first iteration had three load-bearing
problems flagged by a fresh-eyes design review:

1. **A "Phase 2 fittings" section** — screen router, defined-but-unused
   AppMessage outbound slots, untested `nbioPost`, persisted last-formula —
   was a textbook CLAUDE.md violation ("Don't design for hypothetical
   future requirements"). **Cut entirely.** Phase 2, if it ever happens,
   adds what it adds then.
2. **A `GET /api/events?since=midnight` reducer-on-JS approach** that
   would ship ~8–15 KB of per-event JSON over BT-proxied cellular every
   refresh, when the alternative — `GET /api/today` — is ~30 lines of
   Python returning ~150 bytes. **Now Phase 1 server work, not deferred.**
3. **A "Phase 2 teaser toast" on the Down button** that would have trained
   the wrong muscle memory before Phase 2 reassigned it. **Down is now
   reserved for watchface-back forever** (Pebble convention).

Other revisions: AppMessage budget math corrected, sync-dot replaced with
honest "updated X ago" text, fictional brand-constants file removed,
Q1 framing tightened ("no LAN-rescue if it fails — preserve the
tailnet invariant"), Vitest reuse caveated.

## 1. Goal & explicit non-goals

**Goal:** a Pebble Time 2 companion app for NBIO that gives a
glanceable, read-only **today summary** on the wrist. Phase 1 ships the
glance only. Quick-log (wee / poo / formula via Addition) is **designed
in §5 as Phase 2** but not built.

**Non-goals (forever):**

- iOS support. Android is king; iOS second-class. PebbleKit JS network
  behaviour differs across companion apps and we won't dual-track.
- Editing past events on the watch. The PWA is for edits; this is a
  glance + quick-log surface.
- Auth. The tailnet is the perimeter; the companion JS runs on a phone
  on the tailnet; NBIO has no auth. We do not invent any.
- "Replace the PWA." Additive only.

**Non-goals for Phase 1 (deferred, not abandoned):**

- The quick-log screen (designed §5).
- Vit D / tummy-time reminders surfaced on the watch.
- Outbox / offline-log queueing.
- Watchface complications.
- Voice quick-log via the PT2 microphone.

## 2. Why this architecture fits NBIO

```
┌─────────────┐     Bluetooth     ┌─────────────────────────────┐
│ Pebble PT2  │ ◀───AppMessage──▶ │  Pebble Mobile (Android)    │
│  (C app)    │                   │    ┌──────────────────────┐ │
│             │                   │    │ PebbleKit JS sandbox │ │
└─────────────┘                   │    │   (our companion)    │ │
                                  │    └────────┬─────────────┘ │
                                  └─────────────┼───────────────┘
                                                │ XMLHttpRequest
                                       (phone's network stack,
                                        which is on Tailscale)
                                                ▼
                                  ┌─────────────────────────────┐
                                  │  NBIO server on the Pi      │
                                  │  http://<tailnet-host>      │
                                  └─────────────────────────────┘
```

Three reasons it suits NBIO specifically:

1. **Heavy lifting on the phone.** PebbleKit JS runs in a sandbox inside
   the Pebble companion Android app. XMLHttpRequest is the standard sandbox
   network primitive. The phone is already on Tailscale; the XHR uses the
   phone's network stack; Tailscale routing is transparent. **This is the
   load-bearing assumption — Q1 in §9.**
2. **No auth needed, ever.** NBIO trusts the tailnet. Same threat model
   applies. We will *not* invent auth to support a watch.
3. **One small server change for Phase 1.** `GET /api/today` returning a
   compact summary. ~30 lines of Python; payload ~150 B; the watch never
   parses raw events.

## 3. Hardware budget (Pebble Time 2)

- **Display:** 1.5″ 200×228 64-color e-paper, **touchscreen**, RGB-LED
  backlight. Always-on capability is *claimed* by Core Devices but
  not verified hands-on yet — we don't load-bear on it (the overview
  refreshes on wake, not while the display is asleep).
- **Buttons:** 4 tactile — Back (left), Up / Select / Down (right).
  PT2 angled the upper/lower right buttons.
- **Haptic:** linear actuator (crisp short / long / pattern vibes).
- **Sensors:** 6-axis IMU + HR + compass — none load-bearing for Phase 1.
- **AppMessage budget:** default inbox/outbox is ~656 bytes; can be
  negotiated higher with `app_message_open(in_size, out_size)`. The
  spike (§9 Q6) opens **512/512** — comfortably above our realistic
  overview payload (~200–250 B once timestamps and "Materna · 80cc" are
  included) and with headroom we *don't* allocate for Phase 2 because we're
  not designing for Phase 2 (revision finding #1).

After the system status bar (~24 px), usable area is 200 × ~200.

## 4. Screen 1: Overview (the only thing Phase 1 ships)

Optimised for the single most common question: **"when did the baby last
eat, and what does today look like?"** A parent should get the answer in
<0.5 s of wrist glance, no taps.

### Layout

```
┌──────────────────────────────┐
│ 14:32       🔋▮▮▮▮           │  ← system bar (Pebble owns the icons)
├──────────────────────────────┤
│                              │
│        Last fed              │  ← muted label, 12 px
│      2h 14m ago              │  ← BIG, 36 px, sans
│      L · 14 min              │  ← side + duration, 14 px muted
│                              │
├──────────────────────────────┤
│  🤱 6  │  💦 8  │  💩 2      │  ← today's counts, tinted backgrounds
│        │        │            │      (feed=green, wee=blue, poo=brown
│        │        │            │      — derived from app.css tokens)
├──────────────────────────────┤
│ Updated 3m ago      ↓ refresh│  ← honest staleness text + refresh hint
└──────────────────────────────┘
```

Deliberate UX choices (beyond the basics):

- **"Last fed" dominates.** The most-asked question gets the biggest
  pixels. Show relative ("2h 14m ago"), not absolute ("12:18") — the
  question is "how long," not "what time."
- **Subtitle line is type-aware.** If last feed was breast: `L · 14 min`.
  If formula: `80cc · Materna`. One short line, two facts.
- **Color tokens mirror the PWA** (`--feed`, `--wee`, `--poo` from
  `app/nbio/static/app.css`). Familiar palette, no second mental model
  to learn. Spike Q4: verify the closest PT2-palette match for each.
- **Staleness as text, not a coloured dot.** Per the review: with one
  watch and one PWA partner, the only thing the watch *can* know is "did
  my last refresh succeed and when." `Updated 3m ago` says exactly that.
  No tri-color theatre. If a refresh fails, the line reads `Update
  failed (3m ago)` and reuses cached values.
- **Refresh triggers:** on app open, on app wake. **No polling.** Manual
  refresh via the swipe-down gesture (Pebble convention) or the **Up**
  button.

### Physical-button behaviour on the overview

- **Back (left):** back to watchface (Pebble convention; preserved).
- **Up:** refresh now. Spinner + brief haptic. Same as swipe-down.
- **Select:** **does nothing in Phase 1.** No toast, no haptic. If
  Phase 2 ships, Select short-press becomes the button-parity mirror
  for the swipe-right-to-log gesture; until then, silence is honest
  (no swipe hint either — same "no Phase 2 teaser UI" rule).
- **Down:** **back to watchface (Pebble convention).** Reserved
  forever. Phase 2's "log last formula" shortcut, if built, lives on
  *long-press Select*, not Down.

Phase 1 ships zero "Phase 2 teaser" UI. Either an affordance does its
job or it isn't on screen.

## 5. Screen 2: Quick Log (Phase 2 design — for reference, NOT built)

Captured here so a future Phase-2 implementer doesn't re-derive the
design. **Nothing in this section ships in Phase 1.** No code, no
fittings, no scaffolding.

### Entry (Phase 2)

- **Swipe right** from overview — the canonical, touch-first path.
- **Tap Select** from overview — button-parity mirror for users who
  prefer hardware buttons (one-handed-baby-in-the-other scenarios).
- Returns via Back (preserved Pebble convention) or swipe left.

### Layout (Phase 2)

Reviewer math check: 200-px wide canvas, two side-by-side ~80×80 tap
tiles + gutters totals ~180 px wide. Workable. Formula tile underneath
as full-width.

```
┌──────────────────────────────┐
│ ← Log                        │
├──────────────────────────────┤
│                              │
│   ┌────────┐    ┌────────┐   │
│   │  💦    │    │  💩    │   │  ← BIG tap targets, 80×80 each
│   │  WEE   │    │  POO   │   │      single tap = log immediately
│   └────────┘    └────────┘   │
│                              │
│   ┌────────────────────┐     │
│   │  🍼  FORMULA       │     │  ← full-width tile, opens sub-screen
│   │  80cc · Materna ▸  │     │      shows last-used as default text
│   └────────────────────┘     │
│                              │
└──────────────────────────────┘
```

### Wee / Poo (Phase 2)

- Tap → POST `/api/events {type, occurred_at: isoNow(), idempotency_key,
  created_by_device}` via the companion JS.
- Immediate haptic ack (~80 ms).
- Tile flashes green with ✓ ~600 ms.
- Auto-returns to overview; counts reflect the new event.
- **Undo affordance:** for ~4 s after return, the overview shows a
  "↶ undo wee" pill that DELETEs the event on tap. Mirrors NBIO 3am
  ergonomics — every quick action gets a "wait, no" rescue.

### Formula (Phase 2)

```
┌──────────────────────────────┐
│ ← Formula                    │
│  Materna (last used)         │  ← brand shown, NOT editable on watch
├──────────────────────────────┤
│         Total: 75 cc    ↺    │
├──────────────────────────────┤
│  ┌────┐ ┌────┐ ┌────┐        │
│  │ +5 │ │+10 │ │+20 │        │  ← Additive picker only.
│  └────┘ └────┘ └────┘        │      No CUSTOM. No Classic chips.
│  ┌────┐ ┌────┐ ┌────┐        │      Server cap of 500 enforced
│  │+30 │ │+60 │ │+120│        │      client-side (button disabled).
│  └────┘ └────┘ └────┘        │
├──────────────────────────────┤
│      ┌──────────────┐        │
│      │  SAVE  75cc  │        │  ← disabled while total = 0
│      └──────────────┘        │
└──────────────────────────────┘
```

- **Brand source of truth at Phase-2 entry:** the most recent formula
  event in the cached overview payload's `last_feed` field if it was
  formula. If there is no recent formula, the brand line shows
  `(no brand)` and POST omits `formula_brand`. **No hardcoded fallback
  list.** (First-iteration plan invented one; the codebase has no such
  constants and the PWA reads brand history from `/api/feeds/last`.
  If we ever want a constants module, it's a separate refactor.)
- **Submit-disabled on total = 0** matches the PWA Addition mode.
- **The button used to add briefly tints green** (~250 ms) so a touch
  confirms before the total numeral redraws.
- **Long-press SAVE = "silent save"** (no haptic, no animation): useful
  for night feeds where any vibration risks waking the baby.

### Phase-2 long-press shortcut

- **Long-press Select on the overview → log last formula** (POST
  `/api/events` with the brand + volume_ml from the last cached formula
  event, occurred_at = now). Haptic confirm. Undo pill on overview.
  This is the one-handed-no-look ergonomic; it lives on Select, not
  Down (Pebble Down convention is reserved).

## 6. Server change for Phase 1: `GET /api/today`

A new compact summary endpoint. Roughly:

```python
@router.get("/today")
def get_today(conn: sqlite3.Connection = Depends(get_conn)):
    return {
        "today": {
            "feeds": <count: type in {breast, formula}>,
            "wees":  <count: type == wee>,
            "poos":  <count: type == poo>,
            "vit_d_given": <bool>,
            "tummy_minutes": <int>,
            "last_feed": <full feed dict or null>,
        },
        "fetched_at": <iso utc>,
    }
```

Already-existing helpers do the heavy work — `repo.today_counts`,
`repo.daily_totals`, `_today_card`-style reductions in `routes/pages.py`.
The endpoint exposes them as JSON instead of HTML. Phase-1 sized:

- ~30 lines of Python in a route + a thin helper if needed.
- pytest tests: status, shape, counts match `repo.today_counts`, the
  `last_feed` shape matches `/api/feeds/last`.
- No schema or migration — pure derived data.
- Payload ~150 B. AppMessage trivially fits even with `app_message_open`
  at the default 656/656.

The watch never sees `notes`, `actor_name`, `actor_color`,
`idempotency_key`, `created_at`, `updated_at`, `deleted_at`, or any of
the other 11 fields per event that the first-iteration reducer approach
would have streamed for nothing.

## 7. Phase 3 ideas (parked, not committed)

For the record — so they don't get re-derived later:

- **Watchface complication** — "fed 2h ago" tile on the user's
  watchface. Pebble timeline complication API. Big ergonomic win;
  substantial engineering.
- **Wrist-flick navigation** — IMU-driven screen swap.
- **Voice quick-log** — PT2 microphone; rePebble has a voice intent API.
- **Long-press a count to see breakdown** — micro-screen of last N
  timestamps for that type.
- **Vit D / tummy quick-buttons** if/when Phase 2 ships and there's
  spare interaction budget.

## 8. Repo structure

Pebble code lives at `pebble/` in this repo:

```
pebble/
  PLAN.md                  ← this file
  SPIKE_FINDINGS.md        ← produced by §9 spike; commits with Phase 1
  README.md                ← build / install / troubleshoot
  appinfo.json             ← Pebble app manifest
  package.json             ← Pebble's own JS deps (separate from repo-root)
  src/
    c/                     ← watch app (C)
      main.c
      overview_screen.{c,h}
      protocol.h           ← AppMessage key constants (mirrors pkjs)
    pkjs/                  ← PebbleKit JS sandbox
      index.js             ← AppMessage wiring + lifecycle
      api_client.js        ← only `nbioGet` for Phase 1
      storage.js           ← localStorage wrapper (NBIO host URL,
                             last-good payload)
    resources/
      images/
  tests_js/                ← Vitest tests (see Vitest note below)
    api_client.test.js
    storage.test.js
```

### Vitest reuse caveat (per review)

The repo-root `vitest.config.js` (#92) loads `app/nbio/tests_js/setup.js`,
which `eval`s `idb.js` into the jsdom window. Pebble tests don't want
that. Two options when Phase 1 lands:

- **(a) Second Vitest project config** at `pebble/vitest.config.js` with
  its own `setupFiles` (no `idb.js` load); a root npm script runs both.
- **(b) Multiple Vitest "projects"** in the root config — `vitest`
  supports a `projects: [...]` array for exactly this shape.

(b) is cleaner; pick at code time. **The first-iteration plan claimed
"just extend `include`" — that was wrong and is fixed here.**

### Why colocated, not separate repo

- Single GitHub issue tracker.
- The `/api/today` response shape is shared with the watch reducer;
  refactors land in one PR.
- One CI pipeline, one release process.
- If the Pebble ecosystem ever re-dies, deleting `pebble/` is one rm.

`pebble/node_modules/` ignored at repo root via `.gitignore` (same
pattern as the existing `node_modules/` block from #92).

## 9. Spike protocol — answer Q1–Q6 BEFORE any Phase-1 commit

The spike is **one weekend in CloudPebble**, no commits to `pebble/src/`
until the answers are in. Findings land in `pebble/SPIKE_FINDINGS.md`,
which commits as part of the Phase 1 PR alongside `pebble/src/` *if*
the answers are green.

| # | Question | Verification |
|---|---|---|
| Q1 | **Does PebbleKit JS XHR reach a Tailscale-only NBIO host via the Android Pebble companion app?** This is the project pivot. | Hello-world Pebble app that GETs `/api/version` from the Pi over Tailscale and shows the hash on the watch. Test on real PT2 + Android phone. **If Q1 fails: the project ends.** We do *not* "rescue" it by exposing NBIO to the LAN — that violates CLAUDE.md's tailnet-as-perimeter invariant and inflates the threat model 10× to enable a watch. |
| Q2 | XHR round-trip latency over Tailscale-on-cellular AND -on-WiFi? | Time the Q1 round-trip on real network. Goal: p50 < 1 s, p95 < 3 s. |
| Q3 | Does the overview layout (§4) actually fit 200×228 with comfortable tap targets and readable type at arm's length? | Build the layout in the CloudPebble emulator; iterate until "Last fed 2h 14m ago" reads cleanly. |
| Q4 | Nearest PT2-palette match for each of `--feed`/`--wee`/`--poo`/`--vitd`/`--tummy` from `app/nbio/static/app.css`? | Read the token values; pick from [rePebble PT2 palette docs](https://developer.rebble.io/guides/tools-and-resources/hardware-information/). |
| Q5 | Does CloudPebble's emulator support PT2 specifically (vs only Pebble Time / classic)? | Check CloudPebble's emulator target dropdown. If only older targets are listed, all iteration moves to the real device. |
| Q6 | Can `app_message_open(512, 512)` negotiate reliably on PT2? | Open the buffer in the spike app and verify return code. Phase-1 payload (~250 B) fits with margin. |
| Q7 | Battery cost of a dozen overview opens/refreshes per day? | Real-watch test once Q1–Q6 pass. Subjective. |

**Spike timebox:** one focused sitting (a few hours). If Q1 fails, the
project ends cheaply and no production code was ever written.

## 10. Phase 1 — what actually ships

Scoped to the smallest useful glance:

- `pebble/PLAN.md` + `pebble/SPIKE_FINDINGS.md` (this and the spike's writeup).
- `pebble/appinfo.json` + `pebble/package.json` + `pebble/README.md`.
- `pebble/src/c/main.c` + `overview_screen.{c,h}` + `protocol.h`.
- `pebble/src/pkjs/index.js` + `api_client.js` (only `nbioGet`) + `storage.js`.
- Companion JS **settings screen** for the NBIO host URL (Pebble's
  `Pebble.openURL` pattern). The `.pbw` does *not* bake a default host
  URL; first launch shows the settings screen.
- `pebble/tests_js/` for the JS side (Vitest project per §8).
- **Server:** `GET /api/today` route + tests + tiny refactor of
  `_today_card`-style aggregation into a JSON-returning helper.
- CLAUDE.md update: new pointer to `pebble/`, new "Sharp edges" bullet
  for any Pebble-specific gotcha discovered during build.

### What Phase 1 explicitly does NOT ship

(Listed because the first plan iteration had all of these.)

- **No screen router.** Single screen, single window. If Phase 2 wants
  multiple screens, it adds the router then.
- **No `nbioPost`.** Phase 1 issues zero POSTs to NBIO from the watch.
- **No AppMessage outbound slots beyond what the overview needs.**
- **No `STORAGE_KEY_LAST_FORMULA` pre-cache.** Phase 2 fetches this
  fresh if/when Phase 2 ships.
- **No "Phase 2 teaser" UI.** Down is reserved Pebble back; Select is
  silent in Phase 1.

## 11. Phase 1 acceptance criteria

- [ ] **Spike done.** `pebble/SPIKE_FINDINGS.md` committed with answers
      to Q1–Q6 (and Q7 if attempted).
- [ ] `pebble/` repo structure per §8.
- [ ] App builds via `pebble build` or in CloudPebble into a valid `.pbw`.
- [ ] App installs on the PT2 emulator (or, per Q5, on the real watch
      directly if emulator support is absent).
- [ ] App installs on the real Pebble Time 2.
- [ ] Companion JS settings screen accepts an NBIO host URL and persists
      it across launches.
- [ ] First launch with no host URL configured shows the settings screen,
      not a broken overview.
- [ ] On open with a configured host, overview shows feed/wee/poo counts,
      time-since-last-feed, type-aware subtitle — within 2 s warm cache,
      <5 s cold (per Q2 latency target).
- [ ] Up button manually refreshes; spinner + haptic.
- [ ] "Updated X ago" line reflects last successful refresh; reads
      "Update failed (X ago)" on a failed refresh while showing cached
      values.
- [ ] **`GET /api/today` endpoint** exists, returns the shape in §6,
      and is tested. The watch consumes it directly.
- [ ] Vitest tests on `api_client.js` (XHR happy-path + error paths
      reflected in "Updated…" state) and `storage.js` (persist/load host
      URL + cached payload).
- [ ] `pebble/README.md` documents pebble-tool install, emulator run,
      side-load to real watch, and changing the NBIO host URL.
- [ ] CLAUDE.md updated.
- [ ] **Pre-code design review subagent has reviewed this plan** — DONE.
- [ ] **Post-code review subagent has reviewed the implementation** before
      the PR is opened.

## 12. CI strategy

- Phase 1 piggybacks on the existing `js` CI job from #92 — Vitest picks
  up `pebble/tests_js/` via the second-project config (§8).
- No Pebble SDK build in CI for Phase 1 — Pebble SDK + QEMU in container
  is fiddly, not worth the time until there's a release to publish.
- The `GET /api/today` route adds tests under `app/tests/api/` and rides
  the existing pytest matrix.

## 13. Process discipline

- Fresh-eyes subagent review of the plan **before** any code — done.
- Fresh-eyes subagent review of the code **before** opening the PR.
- CLAUDE.md sharp edges + pointer updated when code lands.
- Always open a PR after pushing a green branch.
- The primary debug surface for the Pebble app is the watch itself,
  with the CloudPebble emulator as a faster iteration path when it
  supports PT2 (Q5).

## 14. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Q1 fails** (PebbleKit JS XHR → Tailscale doesn't work). | Unknown — probably-fine-but-unverified, per review. | Spike answers in hours. **No LAN-rescue if it fails.** Project ends; tailnet invariant preserved. |
| Q2 latency makes the app feel sluggish on cellular. | Possible (BT-proxied XHR over cellular is not instant). | `/api/today` payload is tiny so the network is the dominant cost; if even that's too slow, the app caches and shows staleness honestly. |
| PT2 e-paper colour gamut doesn't accommodate our PWA tokens cleanly. | Unknown until Q4. | Pick nearest matches; document divergence; the overview still works monochrome. |
| Pebble ecosystem re-dies. | Medium-low (hardware now open-sourced). | Repo colocation means deleting `pebble/` is trivial. |
| Only one parent has a Pebble; the other relies entirely on the PWA. | High by design. | This is a personal-utility feature, not a parity feature. Both parents using the PWA remains the canonical flow. |
| PT2 always-on display claim turns out not to apply to the colour panel. | Possible (Core Devices marketing isn't perfectly clear on this). | Phase 1 refreshes on wake, not while asleep — no behaviour depends on it. |
| Pebble SDK toolchain rots on a future OS upgrade. | Medium over years. | Pin `pebble-tool` version in `pebble/README.md`; document the Python pin. |

## 15. Follow-up issues to file once this plan is approved

- **"Pebble companion — Phase 2: quick-log screen"** (the §5 design).
- **"Pebble companion — Phase 3: watchface complication."**
- **"Pebble companion — Phase 3: voice quick-log via PT2 mic."**
- **"Pebble companion — outbox queue"** — only if Pi-test surfaces a
  real need.

---

*Sources (June 2026):*
- [coredevices/cloudpebble](https://github.com/coredevices/cloudpebble)
- [rePebble Developer SDK](https://developer.rebble.io/sdk/)
- [PebbleKit JS guide](https://developer.rebble.io/guides/communication/using-pebblekit-js/)
- [PT2 specs — TechCrunch](https://techcrunch.com/2025/08/13/pebbles-smartwatch-is-back-pebble-time-2-specs-revealed/)
- [Hardware Information — rePebble](https://developer.rebble.io/guides/tools-and-resources/hardware-information/)
