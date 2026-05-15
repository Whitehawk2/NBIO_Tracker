/* NBIO Tracker — client app
 * - Device identity, tiles, bottom-sheet modal with time chips
 * - Optimistic insert + idempotency + offline outbox flush
 * - SSE live sync with reconcile
 * - Auto-dark, live "ago" timers, haptics, swipe-to-delete + undo
 */
(function () {
  "use strict";

  const cfg = window.NBIO_CONFIG;
  const IDB = window.NBIO_IDB;

  // ----- helpers
  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const isoNow = () => new Date().toISOString();
  const haptic = (ms = 12) => { try { navigator.vibrate && navigator.vibrate(ms); } catch (_) {} };

  function fmtRel(iso) {
    const dt = new Date(iso);
    const sec = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 1000));
    if (sec < 60) return "just now";
    if (sec < 3600) return Math.floor(sec / 60) + " min ago";
    if (sec < 86400) {
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      return m ? `${h}h ${String(m).padStart(2, "0")}m ago` : `${h}h ago`;
    }
    return Math.floor(sec / 86400) + "d ago";
  }
  function fmtHHMM(iso) {
    const d = new Date(iso);
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  // ----- auto dark (in addition to base.html bootstrap)
  function refreshTheme() {
    const h = new Date().getHours();
    const nightByClock = h >= 19 || h < 7;
    const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.classList.toggle("dark", nightByClock || systemDark);
  }
  setInterval(refreshTheme, 5 * 60 * 1000);
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", refreshTheme);

  // ----- device identity
  const COLORS = ["#4F8BFF", "#9B6BFF", "#3AB974", "#E08AAE", "#E0A040", "#E25D5D"];
  function getDeviceId() {
    let id = localStorage.getItem("nbio.device_id");
    if (!id) { id = "dev-" + uuid(); localStorage.setItem("nbio.device_id", id); }
    return id;
  }
  function getDeviceColor() { return localStorage.getItem("nbio.device_color") || ""; }
  function getDeviceName()  { return localStorage.getItem("nbio.device_name")  || ""; }
  function setDeviceIdentity(color, name) {
    localStorage.setItem("nbio.device_color", color);
    if (name != null) localStorage.setItem("nbio.device_name", name);
    fetch(`${cfg.devicesUrl}/${encodeURIComponent(getDeviceId())}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name || null, color }),
    }).catch(() => {});
  }

  async function ensureOnboarded() {
    if (getDeviceColor()) return;
    return new Promise((resolve) => {
      const backdrop = makeModalShell("Whose phone is this?");
      const body = backdrop.querySelector(".modal-body");

      const nameLabel = document.createElement("div");
      nameLabel.className = "modal-label";
      nameLabel.textContent = "Name (optional)";
      const nameInput = document.createElement("input");
      nameInput.type = "text"; nameInput.placeholder = "Mum, Dad, …"; nameInput.autocomplete = "off";

      const colorLabel = document.createElement("div");
      colorLabel.className = "modal-label";
      colorLabel.textContent = "Pick a colour";
      colorLabel.style.marginTop = "14px";

      const grid = document.createElement("div");
      grid.style.display = "grid"; grid.style.gridTemplateColumns = "repeat(6,1fr)";
      grid.style.gap = "10px";

      let chosen = COLORS[0];
      COLORS.forEach((c) => {
        const sw = document.createElement("button");
        sw.className = "chip"; sw.style.background = c; sw.style.height = "44px"; sw.style.padding = "0";
        sw.setAttribute("aria-label", `colour ${c}`);
        if (c === chosen) sw.classList.add("selected");
        sw.addEventListener("click", () => {
          chosen = c;
          grid.querySelectorAll(".chip").forEach((b) => b.classList.toggle("selected", b === sw));
          haptic(10);
        });
        grid.appendChild(sw);
      });

      const submit = document.createElement("button");
      submit.className = "btn-primary"; submit.textContent = "Save";
      submit.addEventListener("click", () => {
        setDeviceIdentity(chosen, nameInput.value.trim());
        closeModal(backdrop);
        resolve();
      });

      body.append(nameLabel, nameInput, colorLabel, grid, submit);
      document.body.appendChild(backdrop);
    });
  }

  // ----- modal shell
  function makeModalShell(title) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal-sheet" role="dialog" aria-modal="true">
        <div class="modal-grab"></div>
        <div class="modal-title">${title}</div>
        <div class="modal-body"></div>
      </div>
    `;
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeModal(backdrop); });
    return backdrop;
  }
  function closeModal(backdrop) { backdrop.remove(); }

  // ----- time chips
  function buildTimeChips(initialOffsetMin = 0) {
    const state = { offsetSec: initialOffsetMin * 60 };
    const wrap = document.createElement("div");
    wrap.className = "modal-section";

    const readout = document.createElement("div");
    readout.className = "modal-time-readout";
    const chips = document.createElement("div");
    chips.className = "time-chips";

    const buttons = [
      { label: "now", set: 0 },
      { label: "-5m", add: 5 * 60 },
      { label: "-15m", add: 15 * 60 },
      { label: "-30m", add: 30 * 60 },
      { label: "-1h", add: 60 * 60 },
      { label: "-2h", add: 120 * 60 },
      { label: "more…", more: true },
    ];

    const moreInput = document.createElement("input");
    moreInput.type = "datetime-local"; moreInput.style.marginTop = "10px"; moreInput.hidden = true;
    moreInput.addEventListener("input", () => {
      if (!moreInput.value) return;
      const d = new Date(moreInput.value);
      state.offsetSec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
      render();
    });

    function getDate() { return new Date(Date.now() - state.offsetSec * 1000); }
    function render() {
      const d = getDate();
      if (state.offsetSec === 0) {
        readout.innerHTML = `<b>now</b> · ${fmtHHMM(d.toISOString())}`;
      } else {
        readout.innerHTML = `<b>${fmtRel(d.toISOString())}</b> · ${fmtHHMM(d.toISOString())}`;
      }
      $$(".chip[data-label]", chips).forEach((c) => c.classList.toggle("selected",
        (c.dataset.label === "now" && state.offsetSec === 0)));
    }

    buttons.forEach((b) => {
      const btn = document.createElement("button");
      btn.className = "chip"; btn.dataset.label = b.label; btn.textContent = b.label;
      btn.addEventListener("click", () => {
        haptic(8);
        if ("set" in b) state.offsetSec = b.set;
        else if ("add" in b) state.offsetSec += b.add;
        else if (b.more) { moreInput.hidden = !moreInput.hidden; if (!moreInput.hidden) moreInput.focus(); return; }
        render();
      });
      chips.appendChild(btn);
    });

    wrap.append(readout, chips, moreInput);
    render();
    return { el: wrap, getDate };
  }

  // ----- feed modal
  async function openFeedModal(prefill) {
    const backdrop = makeModalShell("🤱 Log feed");
    const body = backdrop.querySelector(".modal-body");

    const time = buildTimeChips(prefill?.offsetMin || 0);
    body.appendChild(time.el);

    // side
    const sideLabel = label("Side");
    const seg = document.createElement("div"); seg.className = "segmented";
    let side = prefill?.feed_side || null;
    let defaultSide = side;
    if (!defaultSide) {
      try {
        const r = await fetch(cfg.lastSideUrl).then((r) => r.json());
        defaultSide = r.last_side === "L" ? "R" : r.last_side === "R" ? "L" : "L";
      } catch (_) { defaultSide = "L"; }
      side = defaultSide;
    }
    for (const s of ["L", "R", "both"]) {
      const b = document.createElement("button");
      b.className = "seg" + (s === side ? " selected" : "");
      b.textContent = s === "both" ? "BOTH" : s === "L" ? "LEFT" : "RIGHT";
      b.dataset.side = s;
      b.addEventListener("click", () => {
        side = s; haptic(8);
        seg.querySelectorAll(".seg").forEach((x) => x.classList.toggle("selected", x.dataset.side === s));
      });
      seg.appendChild(b);
    }
    body.append(sideLabel, wrapSection(seg));

    // duration stepper
    const durLabel = label("Duration (min, optional)");
    let dur = prefill?.feed_duration_min ?? null;
    const stepper = document.createElement("div"); stepper.className = "stepper";
    const minus = document.createElement("button"); minus.textContent = "–"; minus.setAttribute("aria-label","decrease");
    const plus  = document.createElement("button"); plus.textContent = "+";  plus.setAttribute("aria-label","increase");
    const value = document.createElement("div"); value.className = "value";
    const renderDur = () => { value.textContent = dur == null ? "—" : `${dur} min`; };
    minus.addEventListener("click", () => { dur = Math.max(0, (dur ?? 15) - 5); haptic(8); renderDur(); });
    plus.addEventListener( "click", () => { dur = (dur ?? 10) + 5; haptic(8); renderDur(); });
    renderDur();
    stepper.append(minus, value, plus);
    body.append(durLabel, wrapSection(stepper));

    // notes
    const notesLabel = label("Notes (optional)");
    const notes = document.createElement("input"); notes.type = "text"; notes.placeholder = "anything to remember…";
    notes.value = prefill?.notes || "";
    body.append(notesLabel, wrapSection(notes));

    // submit
    const submit = document.createElement("button");
    submit.className = "btn-primary"; submit.textContent = prefill ? "Save changes" : "Save Feed";
    let holdTimer = null, holdFired = false;
    submit.addEventListener("touchstart", () => { holdFired = false; holdTimer = setTimeout(() => { holdFired = true; haptic(40); }, 700); });
    submit.addEventListener("touchend",   () => { clearTimeout(holdTimer); });
    submit.addEventListener("click", async () => {
      submit.disabled = true;
      await submitForm(backdrop, prefill, {
        type: "feed",
        occurred_at: time.getDate().toISOString(),
        feed_side: side,
        feed_duration_min: dur,
        notes: notes.value.trim() || null,
        skip_dup_check: holdFired,
      });
    });
    body.appendChild(submit);
    document.body.appendChild(backdrop);
  }

  // ----- wee modal
  function openWeeModal(prefill) {
    const backdrop = makeModalShell("💦 Log wee");
    const body = backdrop.querySelector(".modal-body");
    const time = buildTimeChips(prefill?.offsetMin || 0);
    body.appendChild(time.el);
    const notesLabel = label("Notes (optional)");
    const notes = document.createElement("input"); notes.type = "text"; notes.placeholder = "leaked, tiny, etc.";
    notes.value = prefill?.notes || "";
    body.append(notesLabel, wrapSection(notes));
    const submit = document.createElement("button");
    submit.className = "btn-primary"; submit.textContent = prefill ? "Save changes" : "Save Wee";
    let holdFired = false, holdTimer = null;
    submit.addEventListener("touchstart", () => { holdTimer = setTimeout(() => { holdFired = true; haptic(40); }, 700); });
    submit.addEventListener("touchend",   () => clearTimeout(holdTimer));
    submit.addEventListener("click", async () => {
      submit.disabled = true;
      await submitForm(backdrop, prefill, {
        type: "wee",
        occurred_at: time.getDate().toISOString(),
        notes: notes.value.trim() || null,
        skip_dup_check: holdFired,
      });
    });
    body.appendChild(submit);
    document.body.appendChild(backdrop);
  }

  // ----- poo modal
  function openPooModal(prefill) {
    const backdrop = makeModalShell("💩 Log poo");
    const body = backdrop.querySelector(".modal-body");
    const time = buildTimeChips(prefill?.offsetMin || 0);
    body.appendChild(time.el);

    const qLabel = label("Type (optional)");
    const grid = document.createElement("div"); grid.className = "quality";
    const labels = ["hard", "lumpy", "cracked", "smooth", "soft", "mushy", "watery"];
    let quality = prefill?.poo_quality || null;
    for (let i = 1; i <= 7; i++) {
      const b = document.createElement("button");
      b.className = "q-chip" + (i === quality ? " selected" : ""); b.dataset.q = i;
      b.innerHTML = `<span class="n">${i}</span><span class="lbl">${labels[i-1]}</span>`;
      b.addEventListener("click", () => {
        quality = (quality === i ? null : i); haptic(8);
        grid.querySelectorAll(".q-chip").forEach((c) => c.classList.toggle("selected", +c.dataset.q === quality));
      });
      grid.appendChild(b);
    }
    body.append(qLabel, wrapSection(grid));

    const notesLabel = label("Notes (optional)");
    const notes = document.createElement("input"); notes.type = "text"; notes.placeholder = "blowout, colour, …";
    notes.value = prefill?.notes || "";
    body.append(notesLabel, wrapSection(notes));

    const submit = document.createElement("button");
    submit.className = "btn-primary"; submit.textContent = prefill ? "Save changes" : "Save Poo";
    let holdFired = false, holdTimer = null;
    submit.addEventListener("touchstart", () => { holdTimer = setTimeout(() => { holdFired = true; haptic(40); }, 700); });
    submit.addEventListener("touchend",   () => clearTimeout(holdTimer));
    submit.addEventListener("click", async () => {
      submit.disabled = true;
      await submitForm(backdrop, prefill, {
        type: "poo",
        occurred_at: time.getDate().toISOString(),
        poo_quality: quality,
        notes: notes.value.trim() || null,
        skip_dup_check: holdFired,
      });
    });
    body.appendChild(submit);
    document.body.appendChild(backdrop);
  }

  function wrapSection(child) {
    const w = document.createElement("div"); w.className = "modal-section"; w.appendChild(child); return w;
  }
  function label(text) {
    const w = document.createElement("div"); w.className = "modal-label"; w.textContent = text;
    return w;
  }

  // ----- submit helpers (create / edit)
  async function submitForm(backdrop, prefill, payload) {
    if (prefill && prefill.id) {
      return submitEdit(backdrop, prefill.id, payload);
    }
    await submitCreate(backdrop, payload);
  }

  async function submitCreate(backdrop, payload) {
    const idem = uuid();
    const fullPayload = {
      ...payload,
      idempotency_key: idem,
      created_by_device: getDeviceId(),
    };

    // optimistic UI
    const optimistic = {
      id: "local:" + idem,
      type: payload.type,
      occurred_at: payload.occurred_at,
      feed_side: payload.feed_side ?? null,
      feed_duration_min: payload.feed_duration_min ?? null,
      poo_quality: payload.poo_quality ?? null,
      notes: payload.notes ?? null,
      actor_color: getDeviceColor() || "#888",
      actor_name: getDeviceName(),
      idempotency_key: idem,
      _pending: true,
    };
    insertOrUpdateRow(optimistic);
    rememberOwnIdem(idem);
    closeModal(backdrop);
    haptic(12);

    let resp = null;
    try {
      const r = await fetch(cfg.eventsUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fullPayload),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      resp = await r.json();
    } catch (_) {
      // queue for later flush
      await IDB.enqueue({ idem, method: "POST", url: cfg.eventsUrl, body: fullPayload, ts: Date.now() });
      bumpPending();
      return;
    }

    // success — reconcile
    if (resp.status === "already_exists") {
      // Server already had it (probably from a prior queued flush). Reconcile silently.
      replaceOptimistic(idem, resp.event);
    } else {
      replaceOptimistic(idem, resp.event);
      if (resp.status === "created_possible_duplicate" && resp.duplicate_of) {
        showDuplicatePrompt(resp.event, resp.duplicate_of);
      }
    }
  }

  async function submitEdit(backdrop, eventId, payload) {
    closeModal(backdrop);
    haptic(10);
    try {
      const r = await fetch(`${cfg.eventsUrl}/${eventId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (r.ok) {
        const data = await r.json();
        insertOrUpdateRow(data.event);
      } else {
        showToast("Couldn't save. Try again.");
      }
    } catch (_) {
      showToast("Offline — edit not saved.");
    }
  }

  // ----- own-idem memory (suppress SSE echoes)
  const ownIdems = new Map();
  function rememberOwnIdem(idem) {
    ownIdems.set(idem, Date.now());
    setTimeout(() => ownIdems.delete(idem), 60 * 1000);
  }

  // ----- row insert / update / remove
  function findRow(ev) {
    const list = $("#event-list");
    if (!list) return null;
    // try by id then by idem
    let r = list.querySelector(`[data-id="${ev.id}"]`);
    if (!r && ev.idempotency_key) r = list.querySelector(`[data-idem="${ev.idempotency_key}"]`);
    return r;
  }

  function ensureList() {
    let list = $("#event-list");
    if (list) return list;
    const wrap = $(".event-list-wrap");
    if (!wrap) return null;
    wrap.querySelector(".empty")?.remove();
    list = document.createElement("ul");
    list.className = "event-list"; list.id = "event-list";
    wrap.appendChild(list);
    return list;
  }

  function rowHTML(ev) {
    const detail =
      ev.type === "feed" ? [(ev.feed_side || ""), ev.feed_duration_min ? `${ev.feed_duration_min}m` : null].filter(Boolean).join(" · ")
      : ev.type === "poo" && ev.poo_quality ? `type ${ev.poo_quality}` : "";
    const tail = ev.notes ? (detail ? ` · ${ev.notes}` : ev.notes) : "";
    const emoji = ev.type === "feed" ? "🤱" : ev.type === "wee" ? "💦" : "💩";
    const color = ev.actor_color || "#888";
    return `
      <span class="ev-emoji" aria-hidden="true">${emoji}</span>
      <span class="ev-time">${fmtHHMM(ev.occurred_at)}</span>
      <span class="ev-rel" data-rel="${ev.occurred_at}">${fmtRel(ev.occurred_at)}</span>
      <span class="ev-detail">${escapeHtml(detail + tail)}</span>
      <span class="ev-actor" style="background:${color}" title="${escapeHtml(ev.actor_name || "")}"></span>
    `;
  }
  function escapeHtml(s) { return String(s ?? "").replace(/[&<>\"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }

  function insertOrUpdateRow(ev) {
    const list = ensureList();
    if (!list) return;
    let row = findRow(ev);
    if (!row) {
      row = document.createElement("li");
      row.className = "event-row fresh";
      list.prepend(row);
      setTimeout(() => row.classList.remove("fresh"), 1500);
    }
    row.dataset.id = ev.id;
    row.dataset.type = ev.type;
    if (ev.idempotency_key) row.dataset.idem = ev.idempotency_key;
    if (ev._pending) row.dataset.pending = "1"; else delete row.dataset.pending;
    row.innerHTML = rowHTML(ev);
    row.__event = ev;
    attachRowGestures(row);
  }

  function replaceOptimistic(idem, ev) {
    const list = $("#event-list");
    if (!list) return;
    const row = list.querySelector(`[data-idem="${idem}"]`);
    if (row) {
      row.dataset.id = ev.id;
      delete row.dataset.pending;
      row.innerHTML = rowHTML(ev);
      row.__event = ev;
      attachRowGestures(row);
    } else {
      insertOrUpdateRow(ev);
    }
  }

  function removeRow(id) {
    const list = $("#event-list"); if (!list) return;
    const row = list.querySelector(`[data-id="${id}"]`);
    if (row) {
      row.classList.add("removing");
      setTimeout(() => row.remove(), 280);
    }
  }

  // ----- row gestures: tap = edit, swipe-left = delete
  function attachRowGestures(row) {
    if (row.__gesturesAttached) return;
    row.__gesturesAttached = true;

    let startX = null, dx = 0;
    row.addEventListener("touchstart", (e) => { startX = e.touches[0].clientX; dx = 0; }, { passive: true });
    row.addEventListener("touchmove", (e) => {
      if (startX == null) return;
      dx = e.touches[0].clientX - startX;
      if (dx < -10) {
        row.classList.add("swiping");
        row.style.transform = `translateX(${Math.max(dx, -160)}px)`;
      }
    }, { passive: true });
    row.addEventListener("touchend", () => {
      row.classList.remove("swiping");
      row.style.transform = "";
      if (dx < -90) doSoftDelete(row);
      startX = null; dx = 0;
    });

    row.addEventListener("click", () => {
      const ev = row.__event;
      if (!ev || !ev.id || String(ev.id).startsWith("local:")) return;
      openEditFor(ev);
    });
  }

  function openEditFor(ev) {
    const prefill = {
      id: ev.id,
      feed_side: ev.feed_side, feed_duration_min: ev.feed_duration_min,
      poo_quality: ev.poo_quality, notes: ev.notes,
      offsetMin: Math.max(0, Math.round((Date.now() - new Date(ev.occurred_at).getTime()) / 60000)),
    };
    if (ev.type === "feed") openFeedModal(prefill);
    else if (ev.type === "wee") openWeeModal(prefill);
    else openPooModal(prefill);
  }

  async function doSoftDelete(row) {
    const id = row.dataset.id;
    if (!id || id.startsWith("local:")) return;
    haptic(20);
    row.classList.add("removing");
    setTimeout(() => row.remove(), 250);
    try {
      const r = await fetch(`${cfg.eventsUrl}/${id}`, { method: "DELETE" });
      if (!r.ok) throw 0;
      showUndoToast(id);
    } catch (_) {
      showToast("Offline — delete will retry");
      // Best-effort: leave the row removed locally; SSE/refresh will reconcile if delete actually failed.
    }
  }

  function showUndoToast(id) {
    const t = document.createElement("div");
    t.className = "toast";
    t.innerHTML = `Deleted · <button>Undo</button>`;
    const btn = t.querySelector("button");
    let alive = true;
    btn.addEventListener("click", async () => {
      alive = false;
      try {
        const r = await fetch(`${cfg.eventsUrl}/${id}/undelete`, { method: "POST" });
        if (r.ok) {
          const data = await r.json();
          insertOrUpdateRow(data.event);
        }
      } catch (_) { /* SSE will reconcile */ }
      t.remove();
    });
    $("#toast-root").appendChild(t);
    setTimeout(() => { if (alive) t.remove(); }, 5000);
  }

  function showToast(text, ms = 3000) {
    const t = document.createElement("div"); t.className = "toast"; t.textContent = text;
    $("#toast-root").appendChild(t);
    setTimeout(() => t.remove(), ms);
  }

  function showDuplicatePrompt(myEvent, dup) {
    const t = document.createElement("div"); t.className = "toast";
    const deltaTxt = Math.abs(dup.delta_seconds) < 60
      ? `${Math.abs(dup.delta_seconds)}s`
      : `${Math.round(Math.abs(dup.delta_seconds)/60)} min`;
    t.innerHTML = `Possible duplicate (${deltaTxt} apart) <button data-keep>Keep</button> <button data-del>Delete mine</button>`;
    t.querySelector("[data-keep]").addEventListener("click", () => t.remove());
    t.querySelector("[data-del]").addEventListener("click", async () => {
      try { await fetch(`${cfg.eventsUrl}/${myEvent.id}`, { method: "DELETE" }); removeRow(myEvent.id); }
      catch (_) {}
      t.remove();
    });
    $("#toast-root").appendChild(t);
    setTimeout(() => t.remove(), 10000);
  }

  // ----- SSE
  let sse = null, sseLastId = 0, sseBackoff = 1000;
  function connectSSE() {
    setSyncState("connecting");
    try { sse?.close(); } catch (_) {}
    sse = new EventSource(cfg.sseUrl);
    sse.onopen = () => { setSyncState("connected"); sseBackoff = 1000; };
    sse.onerror = () => { setSyncState("error"); try { sse.close(); } catch (_) {} setTimeout(connectSSE, Math.min(sseBackoff *= 1.6, 15000)); };
    const handle = (kind) => (msg) => {
      try {
        sseLastId = Math.max(sseLastId, +msg.lastEventId || 0);
        const data = JSON.parse(msg.data);
        if (kind === "deleted") { removeRow(data.id); return; }
        // suppress own echo for created events
        if (kind === "created" && data.idempotency_key && ownIdems.has(data.idempotency_key)) {
          insertOrUpdateRow(data); return;
        }
        insertOrUpdateRow(data);
      } catch (_) {}
    };
    sse.addEventListener("event.created",   handle("created"));
    sse.addEventListener("event.updated",   handle("updated"));
    sse.addEventListener("event.deleted",   handle("deleted"));
    sse.addEventListener("event.undeleted", handle("created"));
    sse.addEventListener("device.updated", () => { /* future: recolour rows */ });
  }
  function setSyncState(state) {
    const dot = $("#sync-badge .sync-dot");
    if (dot) dot.dataset.state = state;
  }

  // ----- outbox flush
  let flushing = false;
  async function flushOutbox() {
    if (flushing) return;
    if (!navigator.onLine) return;
    flushing = true;
    try {
      const items = await IDB.listOutbox();
      for (const it of items) {
        try {
          const r = await fetch(it.url, {
            method: it.method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(it.body),
          });
          if (!r.ok) continue;
          const data = await r.json();
          await IDB.dequeue(it.idem);
          if (data.event) replaceOptimistic(it.idem, data.event);
          if (data.status === "created_possible_duplicate" && data.duplicate_of) {
            showDuplicatePrompt(data.event, data.duplicate_of);
          }
        } catch (_) { /* network died mid-flush */ break; }
      }
    } finally {
      flushing = false;
      const remaining = await IDB.countOutbox();
      updatePendingBadge(remaining);
      if (remaining === 0) setSyncState("connected");
      else setSyncState("offline");
    }
  }
  async function bumpPending() {
    const n = await IDB.countOutbox();
    updatePendingBadge(n);
    setSyncState("offline");
  }
  function updatePendingBadge(n) {
    const el = $("#sync-pending");
    if (!el) return;
    if (n > 0) { el.hidden = false; el.textContent = `${n}↑`; }
    else { el.hidden = true; }
  }

  // ----- live "ago" updater
  function refreshRelTimes() {
    $$("[data-rel]").forEach((el) => { el.textContent = fmtRel(el.dataset.rel); });
  }

  // ----- copy summary (reports)
  function wireCopySummary() {
    const btn = $("#copy-summary");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      const rows = $$("#totals-body tr").map((tr) => {
        const c = tr.querySelectorAll("td");
        return `${c[0].textContent}: ${c[1].textContent} feeds, ${c[2].textContent} wees, ${c[3].textContent} poos${c[4].textContent !== "—" ? " (avg " + c[4].textContent + ")" : ""}`;
      });
      const text = rows.join("\n");
      try { await navigator.clipboard.writeText(text); showToast("Copied!"); }
      catch (_) { showToast("Couldn't copy"); }
    });
  }

  // ----- wire tiles (tap = modal, long-press = log now)
  function wireTiles() {
    const map = { feed: openFeedModal, wee: openWeeModal, poo: openPooModal };
    $$(".tile").forEach((tile) => {
      const type = tile.dataset.type;
      let pressTimer = null, longFired = false;
      const start = () => {
        longFired = false;
        pressTimer = setTimeout(() => {
          longFired = true; haptic(40);
          submitCreate(makeModalShell(""), {
            type,
            occurred_at: isoNow(),
            skip_dup_check: false,
            ...(type === "feed" ? { feed_side: null } : {}),
          });
        }, 600);
      };
      const end = (e) => {
        clearTimeout(pressTimer);
        if (longFired) { e.preventDefault?.(); return; }
      };
      tile.addEventListener("touchstart", start, { passive: true });
      tile.addEventListener("touchend", end);
      tile.addEventListener("touchcancel", () => clearTimeout(pressTimer));
      tile.addEventListener("mousedown", start);
      tile.addEventListener("mouseup", end);
      tile.addEventListener("mouseleave", () => clearTimeout(pressTimer));
      tile.addEventListener("click", (e) => { if (longFired) return e.preventDefault(); haptic(12); map[type]({}); });
    });
  }

  // ----- attach gestures to pre-rendered rows
  function wireExistingRows() {
    $$("#event-list .event-row").forEach((row) => {
      const id = row.dataset.id;
      // hydrate minimal __event from DOM for editing
      const detailText = row.querySelector(".ev-detail")?.textContent || "";
      row.__event = {
        id,
        type: row.dataset.type,
        occurred_at: row.querySelector(".ev-rel")?.dataset.rel,
        notes: null,
        // Fields below are unknown without a fetch; refetch on edit if needed.
      };
      attachRowGestures(row);
    });
  }

  // ----- init
  document.addEventListener("DOMContentLoaded", async () => {
    await ensureOnboarded();
    wireTiles();
    wireExistingRows();
    wireCopySummary();
    refreshRelTimes();
    setInterval(refreshRelTimes, 60 * 1000);

    connectSSE();
    bumpPending();

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        flushOutbox();
        if (!sse || sse.readyState === EventSource.CLOSED) connectSSE();
      }
    });
    window.addEventListener("online", () => { flushOutbox(); connectSSE(); });
    setInterval(flushOutbox, 30 * 1000);
  });
})();
