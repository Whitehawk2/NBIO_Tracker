# Spike Runbook — Pebble Time 2 + NBIO

> **Purpose:** answer Q1–Q6 from `PLAN.md` §9 with minimum ceremony.
> One focused sitting (target: 2–4 hours). All work happens in
> CloudPebble (https://cloudpebble.repebble.com) — no local toolchain
> install yet. The spike code is **throwaway** unless every Q is green;
> if green, the spike code is **promoted to Phase 1** with a reducer +
> the real overview layout layered on top.

## What you need on hand

- Pebble Time 2 paired with the Pebble Android companion app on your
  phone. Confirmed pairing — see the watch's name in the Pebble app's
  "My Pebble" view.
- Your phone on Tailscale, NBIO reachable from the phone's browser at
  `http://<your-tailnet-host>/api/version`. Note the hostname.
- A CloudPebble account at https://cloudpebble.repebble.com (login
  via Rebble account). Empty project slot.
- A pen and paper, or a note in `pebble/SPIKE_FINDINGS.md` open in a
  side window. Each Q has a "record this" line.

If any of those isn't true, stop and fix that first — don't paper over.

## Hello-world skeleton

Create a new CloudPebble project (C + JS, single-window). Target
platform: **Diorite** (Time 2's chip name in the Pebble SDK is
`diorite`, per [rePebble hardware docs](https://developer.rebble.io/guides/tools-and-resources/hardware-information/)).
If the dropdown only offers older targets, that's Q5 — record it
and continue against the closest available platform; the spike still
works on Basalt (Time 1).

### `src/c/main.c`

```c
#include <pebble.h>

static Window  *s_window;
static TextLayer *s_text;
static char     s_buf[128];

// AppMessage keys — must match appKeys in appinfo.json + the JS side.
#define KEY_VERSION_STR  0
#define KEY_LATENCY_MS   1
#define KEY_ERROR_STR    2

static void update_display(const char *line1, const char *line2) {
  // Two lines, separated by a newline. Pebble TextLayer wraps; small
  // enough payload that we don't need anything fancier for the spike.
  snprintf(s_buf, sizeof(s_buf), "%s\n%s", line1, line2 ? line2 : "");
  text_layer_set_text(s_text, s_buf);
}

static void inbox_received(DictionaryIterator *iter, void *context) {
  Tuple *v = dict_find(iter, KEY_VERSION_STR);
  Tuple *l = dict_find(iter, KEY_LATENCY_MS);
  Tuple *e = dict_find(iter, KEY_ERROR_STR);
  if (e) {
    update_display("ERROR", e->value->cstring);
    return;
  }
  if (v && l) {
    char line2[32];
    snprintf(line2, sizeof(line2), "%dms via XHR", (int)l->value->int32);
    update_display(v->value->cstring, line2);
  }
}

static void window_load(Window *window) {
  Layer *root = window_get_root_layer(window);
  GRect b = layer_get_bounds(root);
  s_text = text_layer_create(GRect(0, 40, b.size.w, 100));
  text_layer_set_font(s_text, fonts_get_system_font(FONT_KEY_GOTHIC_28_BOLD));
  text_layer_set_text_alignment(s_text, GTextAlignmentCenter);
  text_layer_set_background_color(s_text, GColorClear);
  update_display("Loading...", "");
  layer_add_child(root, text_layer_get_layer(s_text));
}

static void window_unload(Window *window) {
  text_layer_destroy(s_text);
}

static void init(void) {
  s_window = window_create();
  window_set_window_handlers(s_window, (WindowHandlers){
    .load = window_load, .unload = window_unload,
  });
  window_stack_push(s_window, true);

  app_message_register_inbox_received(inbox_received);

  // Q6 buffer-size negotiation. Open at 512/512 — well above the
  // realistic Phase-1 payload (~250 B) with headroom. Record the
  // AppMessageResult; non-APP_MSG_OK is Q6 fail.
  AppMessageResult r = app_message_open(512, 512);
  APP_LOG(APP_LOG_LEVEL_INFO, "app_message_open(512,512) -> %d", (int)r);
}

static void deinit(void) {
  window_destroy(s_window);
}

int main(void) { init(); app_event_loop(); deinit(); }
```

### `src/pkjs/index.js`

```js
// PebbleKit JS — runs in the Pebble Android app's sandbox.
// Goal: fetch /api/version from NBIO over Tailscale; time the XHR;
// send result to the watch.

// EDIT THIS to your Tailscale hostname (no trailing slash).
var NBIO_HOST = "http://your-pi.tail-scale.ts.net";

Pebble.addEventListener("ready", function () {
  console.log("PKJS ready; NBIO_HOST=" + NBIO_HOST);
  fetchVersion();
});

function fetchVersion() {
  var url = NBIO_HOST + "/api/version";
  var xhr = new XMLHttpRequest();
  var started = Date.now();

  xhr.open("GET", url, true);
  xhr.timeout = 8000;  // 8s — anything over is a fail for Q2.

  xhr.onload = function () {
    var elapsed = Date.now() - started;
    if (xhr.status >= 200 && xhr.status < 300) {
      try {
        var data = JSON.parse(xhr.responseText);
        send({ 0: String(data.version || "?"), 1: elapsed });
      } catch (e) {
        send({ 2: "Bad JSON: " + xhr.responseText.slice(0, 40) });
      }
    } else {
      send({ 2: "HTTP " + xhr.status });
    }
  };
  xhr.onerror   = function () { send({ 2: "XHR error" }); };
  xhr.ontimeout = function () { send({ 2: "Timeout 8s" }); };

  console.log("GET " + url);
  xhr.send();
}

function send(dict) {
  Pebble.sendAppMessage(
    dict,
    function () { console.log("AppMessage sent"); },
    function (e) { console.log("AppMessage FAILED " + JSON.stringify(e)); },
  );
}
```

### `package.json` (auto-generated by CloudPebble; verify it has)

```json
{
  "pebble": {
    "displayName": "NBIO Spike",
    "uuid": "<auto>",
    "sdkVersion": "3",
    "watchapp": { "watchface": false },
    "messageKeys": { "VERSION_STR": 0, "LATENCY_MS": 1, "ERROR_STR": 2 },
    "targetPlatforms": ["diorite", "basalt"]
  }
}
```

(If `diorite` isn't in the SDK's recognised platforms list when you
hit build, that's Q5 — drop it and build for `basalt` only. Watch is
fine to side-load a basalt build; the SDK auto-adapts the binary
where possible.)

## The Q1–Q6 checklist (run in order; stop on a hard fail)

### Q1 — XHR-to-Tailscale through the Pebble Android companion

**Goal:** the watch shows your NBIO `static_assets_hash` (e.g.
`029520bf7cb0`) on screen.

1. Edit `NBIO_HOST` in `src/pkjs/index.js` to your Tailscale URL.
2. CloudPebble → **Compilation** → **Build**. Expect a green build
   (no errors).
3. CloudPebble → **Compilation** → **Install on Phone**. Side-load to
   your PT2 via the Pebble Android app.
4. Open the "NBIO Spike" app on the watch.
5. **Watch the screen.** Within ~3 seconds, expect:
   ```
   029520bf7cb0
   <X>ms via XHR
   ```
6. If you see `ERROR / XHR error` or `ERROR / Timeout 8s`:
   - Open the Pebble Android app → **Settings** → **Developer** →
     **JS Console** (or Logs). Read the actual error.
   - Try the same URL in the phone's Chrome — does it work there?
     If Chrome works but PKJS doesn't, that's a sandbox restriction
     (likely Android cleartext-HTTP block; Tailscale serves HTTP by
     default).
   - **If Chrome works but PKJS doesn't, document the exact error
     and treat as Q1 hard-fail until investigated.** Don't paper
     over with HTTPS or LAN exposure.

**Record:**
- ✅/❌ Q1 (and the error text if ❌).
- If ❌: phone OS version, Pebble Android app version, the JS
  console error verbatim. Filing those into `SPIKE_FINDINGS.md` lets
  the next session decide whether to retry with a workaround.

### Q2 — round-trip latency

If Q1 is green, the watch is already showing latency. Run it 5×:

- Tap **Up** button on the watch → app reloads → triggers another
  fetch (well, this hello-world doesn't bind Up to refresh — just
  exit + re-open from the launcher).
- Record 5 numbers each on Wi-Fi and on cellular.

**Targets:** p50 < 1000 ms, p95 < 3000 ms. Either network on either
metric over 3s is amber; over 5s is red and we revisit the design.

**Record:** the 10 numbers and the medians.

### Q3 — does the overview layout actually fit?

Replace `src/c/main.c` with a layout-only mock — no XHR, just hardcoded
strings rendered into the §4 layout from `PLAN.md`. Goals: tap targets
≥44 px (none in this layout but the count cells should accommodate a
finger), "Last fed 2h 14m ago" readable at arm's length, the bottom
"Updated 3m ago" line discreet but visible.

Sketch (paste this over `main.c` after Q2):

```c
#include <pebble.h>

static Window *s_window;

// Helper: draw a centred string at y with a given font.
static void draw_str(GContext *ctx, int y, const char *s, GFont f,
                     GColor color) {
  graphics_context_set_text_color(ctx, color);
  graphics_draw_text(ctx, s, f, GRect(0, y, 200, 60),
                     GTextOverflowModeWordWrap,
                     GTextAlignmentCenter, NULL);
}

static void draw_overview(Layer *layer, GContext *ctx) {
  GFont small = fonts_get_system_font(FONT_KEY_GOTHIC_14);
  GFont big   = fonts_get_system_font(FONT_KEY_BITHAM_42_LIGHT);
  GFont med   = fonts_get_system_font(FONT_KEY_GOTHIC_18_BOLD);

  draw_str(ctx, 8,   "Last fed",          small, GColorDarkGray);
  draw_str(ctx, 22,  "2h 14m ago",        big,   GColorBlack);
  draw_str(ctx, 76,  "L · 14 min",        small, GColorDarkGray);

  // Count row — three cells, equal width, tinted backgrounds.
  GRect feed = GRect(0,   105, 66, 38);
  GRect wee  = GRect(67,  105, 66, 38);
  GRect poo  = GRect(134, 105, 66, 38);
  graphics_context_set_fill_color(ctx, GColorMintGreen); graphics_fill_rect(ctx, feed, 4, GCornersAll);
  graphics_context_set_fill_color(ctx, GColorPictonBlue); graphics_fill_rect(ctx, wee,  4, GCornersAll);
  graphics_context_set_fill_color(ctx, GColorOrange);   graphics_fill_rect(ctx, poo,  4, GCornersAll);
  draw_str(ctx, 110, "🤱 6", med, GColorBlack);  // crude — these will mis-align;
  draw_str(ctx, 110, "💦 8", med, GColorBlack);  // the spike checks fit, not polish.
  draw_str(ctx, 110, "💩 2", med, GColorBlack);

  draw_str(ctx, 152, "Updated 3m ago", small, GColorDarkGray);
}

static void window_load(Window *w) {
  Layer *root = window_get_root_layer(w);
  layer_set_update_proc(root, draw_overview);
  layer_mark_dirty(root);
}

static void init(void) {
  s_window = window_create();
  window_set_window_handlers(s_window, (WindowHandlers){ .load = window_load });
  window_stack_push(s_window, true);
}
static void deinit(void) { window_destroy(s_window); }
int main(void) { init(); app_event_loop(); deinit(); }
```

Build, install, look at the watch. **At arm's length, in normal indoor
light, can you read "2h 14m ago" in <0.5 s?** Same for the counts?

**Record:**
- ✅/❌ Q3 (and what didn't fit if ❌).
- Photo or notes on the actual rendered layout. Issues to expect:
  emoji width vs Latin glyphs, count cells too narrow, the "Updated"
  line clipped by the bottom edge.
- Adjustments to write into Phase 1 (e.g. "drop emoji from counts,
  use word labels"; "shift count row up 6 px").

### Q4 — colour mapping

Open `app/nbio/static/app.css` in this repo. Pull the values for:
- `--feed` (warm theme: `#6fb59a`)
- `--wee`  (warm theme: `#6ea8d6`)
- `--poo`  (warm theme: `#d2a36a`)
- `--vitd` (warm theme: `#e8b339`)
- `--tummy` (warm theme: `#0a9396`)

Look up the nearest **PT2 64-color palette** entries — the Pebble SDK
exposes them as `GColor*` constants. The
[rePebble palette page](https://developer.rebble.io/guides/tools-and-resources/hardware-information/)
or `pebble-tool palette` should help. Substitutes used in the Q3 mock
were `GColorMintGreen`, `GColorPictonBlue`, `GColorOrange` — confirm
those are reasonable or pick better ones.

**Record:** the five PT2 GColor constants chosen, alongside the source
CSS hex. Note any that diverge ugly (e.g. if `--poo` warm-amber maps to
something that looks beige in PT2's gamut — that's a design issue
for Phase 1).

### Q5 — does CloudPebble emulator support PT2?

In CloudPebble's emulator view, look at the platform dropdown. Targets
typically named: `aplite` (Pebble classic), `basalt` (Time / Time
Steel), `chalk` (Time Round), `diorite` (Time 2). **Is `diorite`
there?**

- If yes: run the Q1–Q3 builds in emulator first before installing on
  the real watch. Speeds iteration.
- If no: every build goes straight to the real PT2. Inconvenient but
  not blocking.

**Record:** ✅/❌ + the available emulator targets list.

### Q6 — AppMessage buffer negotiation

Re-flash the Q1 code (the XHR hello-world). Open the Pebble app's
JS Console. Look for the `APP_LOG` line:

```
app_message_open(512,512) -> 0
```

`0` = `APP_MSG_OK`. Anything else (`2` = `APP_MSG_OUT_OF_MEMORY`,
others) is Q6 fail — fall back to 256/256 and re-test, then 128/128.
Whichever first returns 0 is our negotiated budget.

**Record:** the largest size that returns `APP_MSG_OK`.

### Q7 — battery (optional, only if you have a day)

If Q1–Q6 are green and you have time, leave the spike app installed
and open it ~15× across a day (mimicking real overview usage). Note
the PT2 battery % at start and end. **Anything more than ~5% drop
over a day from these opens is concerning;** PT2 is supposed to last
~30 days idle.

## Decision tree — what to do with the spike code

After running through Q1–Q6:

- **All green (or Q5/Q7 amber only):**
  Promote the spike. Move the spike project into `pebble/src/` in
  this repo. Replace the hello-world XHR with a `GET /api/today`
  call, layer the §4 overview layout (with Q3 adjustments) on top,
  add the settings screen for the host URL, add Vitest tests on
  the JS reducer. That's Phase 1.

- **Q1 red:**
  Stop. Document the error in `SPIKE_FINDINGS.md`. Do **not** expose
  NBIO on the LAN as a workaround — the tailnet-as-perimeter invariant
  is sacred. Close the branch; revisit if/when the PebbleKit JS
  sandbox network story changes.

- **Q2 red (latency > 5s):**
  Stop. The app would feel broken at 3am. Same outcome as Q1 red
  unless Q2 is unambiguously a one-off network issue that retests
  green.

- **Q3 red (layout doesn't fit comfortably):**
  Yellow flag — iterate the layout in CloudPebble's emulator until it
  does, then proceed. Document the final layout in `SPIKE_FINDINGS.md`
  as the source of truth for Phase 1.

- **Q4 red (colours look wrong):**
  Yellow flag — the overview still works monochrome; pick the least
  bad PT2 palette entries and document the divergence. Don't block on
  perfect colour match.

- **Q6 red (can't negotiate 512/512):**
  Yellow flag — fall back to whatever size negotiates; the realistic
  payload is ~250 B so anything ≥ 256 is fine. Document the actual
  budget.

## `SPIKE_FINDINGS.md` template

Write this up after the spike. It commits as part of the Phase 1 PR
(if green) or alone (if red, as a record that the project ended).

```markdown
# Pebble Spike — Findings (YYYY-MM-DD)

Conducted by: <you>
Phone: <make/model + Android version>
Pebble: PT2, firmware <ver>
Pebble Android app: <ver>
NBIO server hash at time of spike: <static_assets_hash>

## Q1 — XHR to Tailscale: ✅/❌
[result; error text if ❌; what the phone's Chrome did with the same URL]

## Q2 — Round-trip latency
Wi-Fi runs (ms): X, X, X, X, X  → median X
Cellular runs (ms): X, X, X, X, X  → median X

## Q3 — Layout fit
[notes; photo if useful; final adjustments]

## Q4 — Colour mapping
| Token   | CSS hex   | PT2 GColor       | Notes |
|---------|-----------|------------------|-------|
| --feed  | #6fb59a   | GColorMintGreen  |       |
| --wee   | #6ea8d6   | GColorPictonBlue |       |
| --poo   | #d2a36a   | GColorOrange     |       |
| --vitd  | #e8b339   | GColorYellow     |       |
| --tummy | #0a9396   | GColorTiffanyBlue|       |

## Q5 — Emulator targets available
[list]

## Q6 — AppMessage buffer
Negotiated: <N>/<N> bytes (APP_MSG_OK).

## Q7 — Battery (if attempted)
Start %: X · End %: X · Opens during the day: X

## Decision
☐ Promote to Phase 1
☐ Iterate on yellow flags first
☐ Project ends — reason: ...
```

## After the spike

If you're proceeding: ping me back with the findings. I'll:

1. Drop `pebble/src/c/main.c` + `overview_screen.{c,h}` + `protocol.h`
   and `pebble/src/pkjs/{index,api_client,storage}.js` against the
   `GET /api/today` endpoint, with the layout adjustments from Q3 and
   colours from Q4 baked in.
2. Write the Vitest tests on `api_client.js` and `storage.js`.
3. Add the `GET /api/today` route + pytest tests on the NBIO side.
4. Run the post-code review subagent on the implementation before
   opening the Phase 1 PR.
5. CLAUDE.md updates for the new `pebble/` pointer + any Pebble-specific
   sharp edges discovered along the way.
