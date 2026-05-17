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

  // ----- discoverability hints (#11)
  // Each hint persists its dismissal in localStorage under
  // `nbio.hint.<name>` = "dismissed". The settings UI (#6) will later
  // reset them by prefix-iterating.
  const HINT_KEYS = {
    firstRow: "nbio.hint.first_row",
    longPress: "nbio.hint.long_press",
    syncDot: "nbio.hint.sync_dot",
  };
  function hintDismissed(key) {
    return localStorage.getItem(key) === "dismissed";
  }
  function dismissHint(key) {
    localStorage.setItem(key, "dismissed");
  }

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

  // ----- time chips + always-visible datetime input
  function buildTimeChips(initialOffsetMin = 0) {
    const state = { offsetSec: initialOffsetMin * 60, chipSticky: initialOffsetMin === 0 ? "now" : null };
    const wrap = document.createElement("div");
    wrap.className = "modal-section time-chooser";

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
    ];

    const dtInput = document.createElement("input");
    dtInput.type = "datetime-local";
    dtInput.className = "datetime-input";
    dtInput.step = "60";

    function getDate() { return new Date(Date.now() - state.offsetSec * 1000); }

    function toLocalInputValue(d) {
      const pad = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    function formatReadout(d) {
      const dow = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][d.getDay()];
      const mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()];
      const today = new Date();
      const sameDay = d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate();
      const dateBit = sameDay ? "today" : `${dow} ${d.getDate()} ${mon}`;
      const rel = state.offsetSec === 0 ? "now" : fmtRel(d.toISOString());
      return `<b>${rel}</b> · ${dateBit}, ${fmtHHMM(d.toISOString())}`;
    }

    function render({ syncInput = true } = {}) {
      const d = getDate();
      readout.innerHTML = formatReadout(d);
      if (syncInput) dtInput.value = toLocalInputValue(d);
      $$(".chip[data-label]", chips).forEach((c) =>
        c.classList.toggle("selected", state.chipSticky === c.dataset.label)
      );
    }

    buttons.forEach((b) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip"; btn.dataset.label = b.label; btn.textContent = b.label;
      btn.addEventListener("click", () => {
        haptic(8);
        if ("set" in b) { state.offsetSec = b.set; state.chipSticky = b.label; }
        else if ("add" in b) { state.offsetSec += b.add; state.chipSticky = null; }
        render();
      });
      chips.appendChild(btn);
    });

    // Editing the input is the user picking a custom time — chips become unselected.
    dtInput.addEventListener("input", () => {
      if (!dtInput.value) return;
      const d = new Date(dtInput.value);
      if (isNaN(d.getTime())) return;
      state.offsetSec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
      state.chipSticky = null;
      render({ syncInput: false });
    });
    // Tap the input on desktop to open the native picker if supported.
    dtInput.addEventListener("click", () => {
      if (typeof dtInput.showPicker === "function") {
        try { dtInput.showPicker(); } catch (_) {}
      }
    });

    wrap.append(readout, chips, dtInput);
    render();
    return { el: wrap, getDate };
  }

  // ----- feed modal (breast)
  async function openFeedModal(prefill) {
    const backdrop = makeModalShell("🤱 Log breast feed");
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
        type: "breast",
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

  // ----- formula modal (bottle)
  // Mirrors openFeedModal — same time chips + notes + 700ms-hold-to-skip-dup,
  // but with brand chips (Materna / Nutrilon / Custom) and volume chips
  // (30…240 cc + Custom) instead of side + duration. Smart-defaults pull
  // the last formula brand+volume from /api/feeds/last.
  async function openFormulaModal(prefill) {
    const backdrop = makeModalShell("🍼 Log formula");
    const body = backdrop.querySelector(".modal-body");

    const time = buildTimeChips(prefill?.offsetMin || 0);
    body.appendChild(time.el);

    // Smart-default lookup: if no prefill brand/volume, fetch the last formula
    // event and use its brand+volume as the defaults.
    let defaultBrand = prefill?.formula_brand || null;
    let defaultVolume = prefill?.formula_volume_ml ?? null;
    if (!defaultBrand && !defaultVolume) {
      try {
        const r = await fetch(cfg.lastFeedUrl || "/api/feeds/last").then((r) => r.json());
        if (r && r.last && r.last.type === "formula") {
          defaultBrand = r.last.formula_brand || null;
          defaultVolume = r.last.formula_volume_ml ?? null;
        }
      } catch (_) { /* keep nulls */ }
    }

    // brand chips
    const brandLabel = label("Brand");
    const brandSeg = document.createElement("div"); brandSeg.className = "segmented";
    let brand = defaultBrand;
    const brandChoices = ["Materna", "Nutrilon", "Custom"];
    const customBrandInput = document.createElement("input");
    customBrandInput.type = "text";
    customBrandInput.placeholder = "brand name…";
    customBrandInput.style.display = "none";
    if (brand && !brandChoices.includes(brand) && brand !== "Custom") {
      // Existing custom value — show input pre-filled
      customBrandInput.value = brand;
      customBrandInput.style.display = "";
    }
    for (const b of brandChoices) {
      const btn = document.createElement("button");
      btn.className = "seg";
      btn.textContent = b.toUpperCase();
      btn.dataset.brand = b;
      const isSelected =
        (b === brand) ||
        (b === "Custom" && brand && !brandChoices.includes(brand));
      if (isSelected) btn.classList.add("selected");
      btn.addEventListener("click", () => {
        haptic(8);
        brandSeg.querySelectorAll(".seg").forEach((x) => x.classList.toggle("selected", x === btn));
        if (b === "Custom") {
          customBrandInput.style.display = "";
          brand = customBrandInput.value.trim() || null;
          setTimeout(() => customBrandInput.focus(), 0);
        } else {
          customBrandInput.style.display = "none";
          brand = b;
        }
      });
      brandSeg.appendChild(btn);
    }
    customBrandInput.addEventListener("input", () => { brand = customBrandInput.value.trim() || null; });
    body.append(brandLabel, wrapSection(brandSeg));
    body.append(wrapSection(customBrandInput));

    // volume chips
    const volLabel = label("Amount (cc)");
    const volSeg = document.createElement("div"); volSeg.className = "segmented-wrap";
    let volume = defaultVolume;
    const volChoices = [30, 60, 90, 120, 150, 180, 210, 240];
    const customVolInput = document.createElement("input");
    customVolInput.type = "number";
    customVolInput.min = "1"; customVolInput.max = "500"; customVolInput.placeholder = "cc";
    customVolInput.style.display = "none";
    if (volume != null && !volChoices.includes(volume)) {
      customVolInput.value = String(volume);
      customVolInput.style.display = "";
    }
    for (const v of volChoices) {
      const btn = document.createElement("button");
      btn.className = "seg";
      btn.textContent = `${v}`;
      btn.dataset.vol = String(v);
      if (v === volume) btn.classList.add("selected");
      btn.addEventListener("click", () => {
        haptic(8);
        volSeg.querySelectorAll(".seg").forEach((x) => x.classList.toggle("selected", x === btn));
        customVolInput.style.display = "none";
        volume = v;
      });
      volSeg.appendChild(btn);
    }
    const customVolBtn = document.createElement("button");
    customVolBtn.className = "seg";
    customVolBtn.textContent = "CUSTOM";
    if (volume != null && !volChoices.includes(volume)) customVolBtn.classList.add("selected");
    customVolBtn.addEventListener("click", () => {
      haptic(8);
      volSeg.querySelectorAll(".seg").forEach((x) => x.classList.toggle("selected", x === customVolBtn));
      customVolInput.style.display = "";
      volume = parseInt(customVolInput.value, 10) || null;
      setTimeout(() => customVolInput.focus(), 0);
    });
    volSeg.appendChild(customVolBtn);
    customVolInput.addEventListener("input", () => {
      const n = parseInt(customVolInput.value, 10);
      volume = (isNaN(n) || n < 1) ? null : n;
    });
    body.append(volLabel, wrapSection(volSeg));
    body.append(wrapSection(customVolInput));

    // notes
    const notesLabel = label("Notes (optional)");
    const notes = document.createElement("input"); notes.type = "text"; notes.placeholder = "anything to remember…";
    notes.value = prefill?.notes || "";
    body.append(notesLabel, wrapSection(notes));

    // submit
    const submit = document.createElement("button");
    submit.className = "btn-primary"; submit.textContent = prefill ? "Save changes" : "Save Formula";
    let holdTimer = null, holdFired = false;
    submit.addEventListener("touchstart", () => { holdFired = false; holdTimer = setTimeout(() => { holdFired = true; haptic(40); }, 700); });
    submit.addEventListener("touchend",   () => { clearTimeout(holdTimer); });
    submit.addEventListener("click", async () => {
      submit.disabled = true;
      await submitForm(backdrop, prefill, {
        type: "formula",
        occurred_at: time.getDate().toISOString(),
        formula_brand: brand,
        formula_volume_ml: volume,
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
      // Formula fields need to propagate to bumpOverviews so the
      // today-formula-strip + last-3-days cc cell can update without
      // a reload. (v1.1.0 regression — pre-fix these were missing.)
      formula_brand: payload.formula_brand ?? null,
      formula_volume_ml: payload.formula_volume_ml ?? null,
      actor_color: getDeviceColor() || "#888",
      actor_name: getDeviceName(),
      idempotency_key: idem,
      _pending: true,
    };
    insertOrUpdateRow(optimistic);
    bumpOverviews(optimistic, +1);
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

  // ----- own-echo memory (suppress SSE echoes on the page that
  // initiated the action — we've already updated the UI optimistically).
  const ownIdems = new Map();
  function rememberOwnIdem(idem) {
    ownIdems.set(idem, Date.now());
    setTimeout(() => ownIdems.delete(idem), 60 * 1000);
  }
  // ownDeletes: ids we just deleted locally. The SSE event.deleted echo
  // would otherwise bump bumpOverviews a SECOND time, double-decrementing
  // the cc total (v1.1.0 regression: 245 → 125 → 5 → clamp at 0).
  const ownDeletes = new Map();
  function rememberOwnDelete(id) {
    if (!id) return;
    ownDeletes.set(String(id), Date.now());
    setTimeout(() => ownDeletes.delete(String(id)), 60 * 1000);
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
    let detail = "";
    if (ev.type === "breast") {
      detail = [(ev.feed_side || ""), ev.feed_duration_min ? `${ev.feed_duration_min}m` : null].filter(Boolean).join(" · ");
    } else if (ev.type === "formula") {
      detail = [(ev.formula_brand || ""), ev.formula_volume_ml ? `${ev.formula_volume_ml} cc` : null].filter(Boolean).join(" · ");
    } else if (ev.type === "poo" && ev.poo_quality) {
      detail = `type ${ev.poo_quality}`;
    }
    // 📝 icon signals notes exist; the full text is revealed in the
    // edit modal. Inline notes text was dropped (long notes overlapped
    // the relative-time column on phones — v1.1.0 regression).
    const emoji = ev.type === "breast" ? "🤱" : ev.type === "formula" ? "🍼" : ev.type === "wee" ? "💦" : "💩";
    const color = ev.actor_color || "#888";
    const notesIcon = ev.notes
      ? `<span class="ev-notes-icon" aria-label="has notes" title="has notes">📝</span>`
      : "";
    return `
      <span class="ev-emoji" aria-hidden="true">${emoji}</span>
      <span class="ev-time">${fmtHHMM(ev.occurred_at)}</span>
      <span class="ev-rel" data-rel="${ev.occurred_at}">${fmtRel(ev.occurred_at)}</span>
      <span class="ev-detail">${notesIcon}${escapeHtml(detail)}</span>
      <span class="ev-actor" style="background:${color}" title="${escapeHtml(ev.actor_name || "")}"></span>
      <button type="button" class="row-menu" data-row-menu aria-label="Row actions">⋯</button>
    `;
  }
  function escapeHtml(s) { return String(s ?? "").replace(/[&<>\"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }

  function localISODate(iso) {
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  }

  function insertOrUpdateRow(ev) {
    const list = ensureList();
    if (!list) return;
    let row = findRow(ev);
    if (!row) {
      row = document.createElement("li");
      row.className = "event-row fresh";
      const day = localISODate(ev.occurred_at);
      const header = list.querySelector(`.day-header[data-day="${day}"]`);
      if (header) {
        header.insertAdjacentElement("afterend", row);
      } else {
        list.prepend(row);
      }
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

  // ----- reactive overview refresh (issue #28 #2)
  //
  // After a successful POST or an `event.created` SSE message, increment the
  // matching count in the today-card and the last-3-days mini-table cell.
  // Decrement on `event.deleted`, increment back on undelete. Pure DOM —
  // no API roundtrip; the server's authoritative aggregations land on the
  // next page load and override these.
  //
  // Local-tz aware: we bucket each event by the BROWSER's local date so
  // the optimistic update matches the server-rendered local-date bucketing
  // in pages._group_events_by_local_day / repo.daily_totals.

  // Map event type → today-card count key (breast+formula combined as "feed")
  function countKey(eventType) {
    if (eventType === "breast" || eventType === "formula") return "feed";
    if (eventType === "wee" || eventType === "poo") return eventType;
    return null;
  }

  // YYYY-MM-DD in the browser's local time. Mirrors the server's
  // local-tz bucketing semantics.
  function localDay(isoUtc) {
    const d = new Date(isoUtc);
    if (isNaN(d.getTime())) return null;
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  // The today-formula-strip has two rendering branches: populated
  // (when cc total > 0) and empty (`no formula today`). When an
  // optimistic POST crosses the zero boundary in either direction,
  // we have to swap branches — not just edit a number.
  function renderFormulaStrip(totalCC) {
    const strip = document.querySelector("[data-formula-strip]");
    if (!strip) return;
    if (totalCC > 0) {
      strip.innerHTML =
        `<span class="emoji" aria-hidden="true">🍼</span>` +
        `<span class="label">Today</span>` +
        `<b data-count="formula_ml">${totalCC}</b>` +
        `<span class="unit">cc formula</span>`;
    } else {
      strip.innerHTML =
        `<span class="emoji" aria-hidden="true">🍼</span>` +
        `<span class="muted">no formula today</span>` +
        `<b data-count="formula_ml" hidden>0</b>`;
    }
  }

  function bumpOverviews(ev, delta) {
    const key = countKey(ev?.type);
    if (!key) return;
    const eventDay = localDay(ev.occurred_at);
    if (!eventDay) return;
    const todayDay = localDay(new Date().toISOString());

    // today-card: only bump if the event belongs to local-today
    if (eventDay === todayDay) {
      const cell = document.querySelector(`#today-card [data-count="${key}"]`);
      if (cell) {
        const cur = parseInt(cell.textContent, 10) || 0;
        cell.textContent = String(Math.max(0, cur + delta));
      }
      // Formula cc total — bump by the event's volume_ml (signed by delta).
      if (ev.type === "formula" && ev.formula_volume_ml) {
        const mlCell = document.querySelector(`#today-card [data-count="formula_ml"]`);
        if (mlCell) {
          const cur = parseInt(mlCell.textContent, 10) || 0;
          const next = Math.max(0, cur + delta * ev.formula_volume_ml);
          renderFormulaStrip(next);
        }
      }
    }

    // last-days mini-table: bump if the day matches any visible row
    const row = document.querySelector(`.last-days-table tr[data-day="${eventDay}"]`);
    if (row) {
      const td = row.querySelector(`td[data-col="${key}"]`);
      if (td) {
        // Strip any trailing whitespace/markup (the poo column has a hint span)
        const hint = td.querySelector(".hint");
        const cur = parseInt(td.firstChild?.textContent || td.textContent, 10) || 0;
        const next = Math.max(0, cur + delta);
        // Rewrite first text node so we preserve sibling spans (hint, etc.)
        if (td.firstChild && td.firstChild.nodeType === Node.TEXT_NODE) {
          td.firstChild.nodeValue = String(next);
        } else {
          td.insertBefore(document.createTextNode(String(next)), td.firstChild);
        }
        // Hint dot only makes sense when count is zero; remove if it now has data
        if (hint && next > 0) hint.remove();
      }
      // Formula cc cell — bump by volume_ml (signed).
      if (ev.type === "formula" && ev.formula_volume_ml) {
        const mlTd = row.querySelector(`td[data-col="formula_ml"]`);
        if (mlTd) {
          const cur = parseInt(mlTd.textContent, 10) || 0;
          mlTd.textContent = String(Math.max(0, cur + delta * ev.formula_volume_ml));
        }
      }
    }
  }

  // ----- row gestures: tap = edit, swipe-left = delete, ⋯ = action sheet
  function attachRowGestures(row) {
    if (row.__gesturesAttached) return;
    row.__gesturesAttached = true;

    let startX = null, dx = 0;
    // Touches that start on the `.row-menu` button must not initiate a
    // swipe — otherwise the button can never be tapped on a touch
    // device (the row would eat the gesture).
    row.addEventListener("touchstart", (e) => {
      if (e.target && e.target.closest && e.target.closest(".row-menu")) {
        startX = null;
        return;
      }
      startX = e.touches[0].clientX; dx = 0;
    }, { passive: true });
    row.addEventListener("touchmove", (e) => {
      if (startX == null) return;
      if (e.target && e.target.closest && e.target.closest(".row-menu")) return;
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

    row.addEventListener("click", (e) => {
      // The `⋯` button has its own click handler — let it run, not us.
      if (e.target && e.target.closest && e.target.closest(".row-menu")) return;
      const ev = row.__event;
      if (!ev || !ev.id || String(ev.id).startsWith("local:")) return;
      openEditFor(ev);
    });

    wireRowMenu(row);
  }

  function wireRowMenu(row) {
    const btn = row && row.querySelector ? row.querySelector(".row-menu") : null;
    if (!btn) return;
    btn.addEventListener("click", (e) => {
      // The `.row-menu` button is inside the row, so its click bubbles
      // up to the row's tap-to-edit handler. stopPropagation() prevents
      // both that AND any future delegated handlers from firing.
      e.stopPropagation();
      e.preventDefault();
      const ev = row.__event;
      if (!ev) return;
      openRowActionSheet(row, ev);
    });
  }

  function openRowActionSheet(row, ev) {
    const backdrop = makeModalShell("Actions");
    const body = backdrop.querySelector(".modal-body");

    const editBtn = document.createElement("button");
    editBtn.className = "btn-secondary";
    editBtn.textContent = "Edit";
    editBtn.style.width = "100%";
    editBtn.style.marginBottom = "10px";
    editBtn.addEventListener("click", () => {
      closeModal(backdrop);
      openEditFor(ev);
    });

    const delBtn = document.createElement("button");
    delBtn.className = "btn-secondary";
    delBtn.textContent = "Delete";
    delBtn.style.width = "100%";
    delBtn.style.color = "#c95757";
    delBtn.addEventListener("click", () => {
      closeModal(backdrop);
      doSoftDelete(row);
    });

    body.append(editBtn, delBtn);
    document.body.appendChild(backdrop);
  }

  async function openEditFor(ev) {
    // Server-rendered rows hydrate __event with `notes: null` because
    // not every field lives in a DOM attribute. Fetch the canonical
    // row from the API before opening the modal so notes (and any
    // other fields the row didn't expose) populate correctly.
    // See issue #28 finding #4.
    let full = ev;
    if (ev.id) {
      try {
        const r = await fetch(`${cfg.eventsUrl}/${ev.id}`);
        if (r.ok) {
          const body = await r.json();
          if (body && body.event) full = body.event;
        }
      } catch (_) { /* keep optimistic prefill if the fetch fails */ }
    }
    const prefill = {
      id: full.id,
      feed_side: full.feed_side, feed_duration_min: full.feed_duration_min,
      poo_quality: full.poo_quality, notes: full.notes,
      formula_brand: full.formula_brand, formula_volume_ml: full.formula_volume_ml,
      offsetMin: Math.max(0, Math.round((Date.now() - new Date(full.occurred_at).getTime()) / 60000)),
    };
    if (full.type === "breast") openFeedModal(prefill);
    else if (full.type === "formula") openFormulaModal(prefill);
    else if (full.type === "wee") openWeeModal(prefill);
    else openPooModal(prefill);
  }

  async function doSoftDelete(row) {
    const id = row.dataset.id;
    if (!id || id.startsWith("local:")) return;
    haptic(20);
    const deleted = row.__event;  // capture before removal for the undo path
    // Remember BEFORE we bump locally — the SSE echo may race us back.
    rememberOwnDelete(id);
    row.classList.add("removing");
    setTimeout(() => row.remove(), 250);
    if (deleted) bumpOverviews(deleted, -1);
    try {
      const r = await fetch(`${cfg.eventsUrl}/${id}`, { method: "DELETE" });
      if (!r.ok) throw 0;
      showUndoToast(id, deleted);
    } catch (_) {
      showToast("Offline — delete will retry");
      // Best-effort: leave the row removed locally; SSE/refresh will reconcile if delete actually failed.
    }
  }

  function showUndoToast(id, deleted) {
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
          bumpOverviews(data.event || deleted, +1);
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
        if (kind === "deleted") {
          // Suppress own-echo: if the current page initiated this delete,
          // doSoftDelete already bumped + animated the row out. Bumping
          // again here would double-decrement the cc total (v1.1.0
          // regression).
          const ownEchoDel = data.id && ownDeletes.has(String(data.id));
          const row = document.querySelector(`.event-row[data-id="${data.id}"]`);
          if (!ownEchoDel && row?.__event) bumpOverviews(row.__event, -1);
          removeRow(data.id);
          return;
        }
        // suppress own-echo bump for created events (we already bumped on POST)
        const ownEcho = kind === "created" && data.idempotency_key && ownIdems.has(data.idempotency_key);
        if (kind === "created" && !ownEcho) bumpOverviews(data, +1);
        if (kind === "undeleted") bumpOverviews(data, +1);
        insertOrUpdateRow(data);
      } catch (_) {}
    };
    sse.addEventListener("event.created",   handle("created"));
    sse.addEventListener("event.updated",   handle("updated"));
    sse.addEventListener("event.deleted",   handle("deleted"));
    sse.addEventListener("event.undeleted", handle("undeleted"));
    sse.addEventListener("device.updated", () => { /* future: recolour rows */ });
  }
  const SYNC_LABELS = {
    connecting: "Connection: connecting",
    connected: "Connection: live",
    offline: "Connection: offline (changes queued)",
    error: "Connection: error",
  };
  function setSyncState(state) {
    const dot = $("#sync-badge .sync-dot");
    if (dot) dot.dataset.state = state;
    const btn = $("#sync-badge [data-sync-explain]");
    if (btn) {
      const label = SYNC_LABELS[state] || "Connection status";
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
    }
  }

  // ----- inline hints (#11)
  // Each `[data-hint]` element starts `hidden` server-side. On load we
  // unhide it unless the dismissal flag is set, and bind its
  // `.hint-dismiss` button to persist the dismissal + remove the node.
  const HINT_KEY_BY_NAME = {
    "long-press": HINT_KEYS.longPress,
    "first-row": HINT_KEYS.firstRow,
  };
  function wireHints() {
    $$("[data-hint]").forEach((el) => {
      const name = el.dataset.hint;
      const key = HINT_KEY_BY_NAME[name];
      if (!key) return;
      if (hintDismissed(key)) {
        el.remove();
        return;
      }
      el.hidden = false;
      const btn = el.querySelector(".hint-dismiss");
      if (btn) {
        btn.addEventListener("click", (e) => {
          // Don't let the dismiss bubble to the tile / row click.
          e.stopPropagation();
          e.preventDefault();
          dismissHint(key);
          el.remove();
        });
      }
    });
  }

  // ----- sync-dot tap-to-explain (#11)
  // Tapping the dot opens a small popover listing the four states so a
  // two-parent setup can learn what the colours mean. Dismissal flag
  // only suppresses the auto-open-on-first-connect path; explicit
  // taps always re-open.
  function wireSyncDot() {
    const btn = $("#sync-badge [data-sync-explain]");
    if (!btn) return;
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      openSyncPopover();
    });
  }
  function openSyncPopover() {
    // Reuse the modal backdrop for outside-click dismissal; the inner
    // shell is a small top-anchored card rather than the bottom sheet.
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop sync-popover-backdrop";
    backdrop.innerHTML = `
      <div class="sync-popover" role="dialog" aria-modal="true" aria-label="Connection states" tabindex="-1">
        <div class="sync-popover-title">Connection</div>
        <ul class="sync-popover-list">
          <li><span class="sync-dot" data-state="connected"></span> Live — events sync instantly</li>
          <li><span class="sync-dot" data-state="connecting"></span> Connecting</li>
          <li><span class="sync-dot" data-state="offline"></span> Offline — changes queued</li>
          <li><span class="sync-dot" data-state="error"></span> Error — retrying</li>
        </ul>
        <button type="button" class="btn-secondary sync-popover-dismiss">Got it</button>
      </div>
    `;
    const close = () => {
      dismissHint(HINT_KEYS.syncDot);
      backdrop.remove();
    };
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector(".sync-popover-dismiss").addEventListener("click", close);
    document.body.appendChild(backdrop);
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

  // Tap-to-show-detail on reports timeline marks (#11.2 follow-up).
  // SVG <title> children only render on hover, so touch devices saw no
  // tooltip. Bind click handlers; on tap we read the rect's <title>
  // text and surface it in a transient toast.
  function wireTimelineMarks() {
    $$(".timeline .mark").forEach((rect) => {
      const title = rect.querySelector("title");
      if (!title) return;
      rect.style.cursor = "pointer";
      rect.addEventListener("click", (e) => {
        e.stopPropagation();
        const text = title.textContent.trim();
        if (text) showToast(text, 4000);
      });
    });
  }

  // ----- wire tiles (tap = modal, long-press = log now)
  function wireTiles() {
    const map = {
      breast: openFeedModal,
      formula: openFormulaModal,
      wee: openWeeModal,
      poo: openPooModal,
    };
    // Hold-to-quick-log: 3-second timer, cancelled the moment the finger
    // moves more than MOVE_THRESHOLD px (so page-scroll never accidentally
    // logs an entry). 600ms was too short — kids of finger-tremor or scroll
    // intent could trip it. See production-finding #28 #2 follow-up.
    const LONG_PRESS_MS = 3000;
    const MOVE_THRESHOLD = 10;
    $$(".tile").forEach((tile) => {
      const type = tile.dataset.type;
      if (!(type in map)) return;
      let pressTimer = null;
      let longFired = false;
      let movedDuringTouch = false;
      let startX = 0, startY = 0;
      const cancel = () => {
        if (pressTimer !== null) {
          clearTimeout(pressTimer);
          pressTimer = null;
        }
      };
      const start = (e) => {
        longFired = false;
        movedDuringTouch = false;
        const t = e.touches?.[0];
        if (t) { startX = t.clientX; startY = t.clientY; }
        else if (e.clientX !== undefined) { startX = e.clientX; startY = e.clientY; }
        pressTimer = setTimeout(() => {
          longFired = true; haptic(40);
          submitCreate(makeModalShell(""), {
            type,
            occurred_at: isoNow(),
            skip_dup_check: false,
            ...(type === "breast" ? { feed_side: null } : {}),
          });
        }, LONG_PRESS_MS);
      };
      const move = (e) => {
        if (pressTimer === null) return;
        const t = e.touches?.[0] ?? e;
        if (t.clientX === undefined) return;
        if (Math.abs(t.clientX - startX) > MOVE_THRESHOLD
            || Math.abs(t.clientY - startY) > MOVE_THRESHOLD) {
          movedDuringTouch = true;
          cancel();
        }
      };
      const end = (e) => {
        cancel();
        if (longFired) { e.preventDefault?.(); return; }
      };
      tile.addEventListener("touchstart", start, { passive: true });
      tile.addEventListener("touchmove", move, { passive: true });
      tile.addEventListener("touchend", end);
      tile.addEventListener("touchcancel", cancel);
      tile.addEventListener("mousedown", start);
      tile.addEventListener("mousemove", move);
      tile.addEventListener("mouseup", end);
      tile.addEventListener("mouseleave", cancel);
      tile.addEventListener("click", (e) => {
        // Suppress click if either: long-press fired (already logged), or the
        // user was scrolling/dragging when they touched the tile.
        if (longFired || movedDuringTouch) { e.preventDefault(); return; }
        haptic(12);
        map[type]({});
      });
    });
  }

  // ----- attach gestures to pre-rendered rows
  function wireExistingRows() {
    $$("#event-list .event-row").forEach((row) => {
      const id = row.dataset.id;
      // hydrate minimal __event from DOM for editing + delete-bump
      const volRaw = row.dataset.formulaVolumeMl;
      const volume_ml = volRaw ? parseInt(volRaw, 10) : null;
      row.__event = {
        id,
        type: row.dataset.type,
        occurred_at: row.querySelector(".ev-rel")?.dataset.rel,
        notes: null,
        // formula_volume_ml needs to be present so bumpOverviews can
        // decrement the cc total when this row is deleted. Without it
        // (pre-fix), deleting a server-rendered formula row left the
        // today-formula-strip stale until reload.
        formula_volume_ml: volume_ml,
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
    wireTimelineMarks();
    wireSyncDot();
    wireHints();
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

    registerServiceWorker();
  });

  /* ----- Service worker registration + "Update available" toast
   *
   * The server-side /static/sw.js route (routes/sw.py) returns the SW
   * with the cache name templated to a hash of the current static
   * tree. When the shell changes, the browser fetches the new SW,
   * installs it, activates it — and because the cache name differs
   * from the previously-installed SW's, the activate handler purges
   * the old cache. The next page load fetches the fresh shell.
   *
   * The user-visible toast: when an UPDATE (not a first install)
   * completes, the new SW becomes the controller via skipWaiting +
   * clients.claim. The toast tells the user "tap to reload" so the
   * page picks up the new JS that the new SW has now cached.
   * navigator.serviceWorker.controller is truthy only on subsequent
   * registrations — that's how we differentiate first install from
   * update.  (See issue #23.)
   */
  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    const hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.register("/static/sw.js").then((reg) => {
      reg.addEventListener("updatefound", () => {
        const newWorker = reg.installing;
        if (!newWorker) return;
        newWorker.addEventListener("statechange", () => {
          if (newWorker.state === "activated" && hadController) {
            showUpdateAvailableToast();
          }
        });
      });
    }).catch(console.warn);
  }

  function showUpdateAvailableToast() {
    const root = $("#toast-root");
    if (!root) return;
    // Don't stack multiple update toasts on the same page
    if (root.querySelector(".toast-update")) return;
    const t = document.createElement("div");
    t.className = "toast toast-update";
    t.innerHTML = `Update available · <button>Reload</button>`;
    t.querySelector("button").addEventListener("click", () => {
      window.location.reload();
    });
    root.appendChild(t);
    // Sticky on purpose — let the user decide when to reload
  }
})();
