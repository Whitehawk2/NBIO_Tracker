// @ts-check
// Seeds a deterministic fixture set into the (ephemeral) app DB before specs
// run, via the real HTTP API. The app boots with DUP_WINDOW_SECONDS=0 so seeds
// never trip duplicate detection; we also pass skip_dup_check defensively.
//
// Timestamps are NOW-RELATIVE to *today* (UTC, matching the app's TZ=UTC) per
// the project's date-fixture rule (CLAUDE.md / #78): no hardcoded calendar
// dates that would drift into a different "last 3 days" window over time.

const BASE_URL = process.env.BASE_URL || "http://localhost:8000";

async function waitForHealth(timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  let lastErr;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${BASE_URL}/healthz`);
      if (r.ok) return;
    } catch (e) {
      lastErr = e;
    }
    await new Promise((res) => setTimeout(res, 500));
  }
  throw new Error(`app /healthz not ready after ${timeoutMs}ms (${BASE_URL}): ${lastErr}`);
}

async function putDevice(id, name, color) {
  const r = await fetch(`${BASE_URL}/api/devices/${id}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name, color }),
  });
  if (!r.ok) throw new Error(`seed device ${id} -> ${r.status}: ${await r.text()}`);
}

async function postEvent(ev) {
  const r = await fetch(`${BASE_URL}/api/events`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ created_by_device: "seed-parent-a", skip_dup_check: true, ...ev }),
  });
  if (!r.ok) throw new Error(`seed event (${ev.type}) -> ${r.status}: ${await r.text()}`);
  return r.json();
}

// An ISO-8601 UTC timestamp at hour `h` *today*. Daytime hours keep each seed
// clear of a local-midnight boundary so its own day bucket is stable. NOTE: the
// reactivity spec asserts these land in "today" relative to its OWN runtime
// clock; the seed and the spec disagree only if the whole suite straddles UTC
// midnight between this seeding and the spec (a ~seconds window). Accepted as
// negligible per the #78 date-fixture rule (now-relative, not a hardcoded date).
function todayAtUTC(h) {
  const d = new Date();
  d.setUTCHours(h, 0, 0, 0);
  return d.toISOString();
}

module.exports = async () => {
  await waitForHealth();

  await putDevice("seed-parent-a", "Parent A (seed)", "#4F8BFF");

  // Two formula feeds today => a real server-side aggregate (120 cc) at first
  // paint, so the reactivity spec asserts a DELTA on top of a hydrated count
  // rather than counting client-held rows (which would undercount history older
  // than the 3-day window — the #93 trap).
  const seeds = [
    { type: "breast", feed_side: "both", feed_duration_min: 15, occurred_at: todayAtUTC(8), idempotency_key: "seed-breast-0800" },
    { type: "formula", formula_volume_ml: 60, formula_brand: "Materna", occurred_at: todayAtUTC(9), idempotency_key: "seed-formula-0900" },
    { type: "wee", occurred_at: todayAtUTC(10), idempotency_key: "seed-wee-1000" },
    { type: "poo", poo_quality: 4, occurred_at: todayAtUTC(11), idempotency_key: "seed-poo-1100" },
    { type: "formula", formula_volume_ml: 60, formula_brand: "Materna", occurred_at: todayAtUTC(12), idempotency_key: "seed-formula-1200" },
  ];
  for (const s of seeds) await postEvent(s);
};
