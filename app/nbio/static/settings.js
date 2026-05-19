/* NBIO Tracker — Settings page wiring
 *
 * Forms POST/PATCH/PUT via fetch + JSON. Toasts on success/failure.
 * Theme picker writes localStorage + dataset.theme; base.html's
 * inline bootstrap reads them pre-paint so cold loads don't flash.
 *
 * Sends X-Device-Id on every write so the future `current_actor`
 * dependency resolves correctly. Today this is opaque to the body
 * (the actor is a Depends parameter; routes don't read it); future
 * auth swap-in benefits from the pre-existing wiring.
 */
(function () {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ---------- shared helpers ----------

  function getDeviceId() {
    try { return localStorage.getItem("nbio.device_id") || ""; } catch (_) { return ""; }
  }
  function getDeviceColor() {
    try { return localStorage.getItem("nbio.device_color") || ""; } catch (_) { return ""; }
  }
  function getDeviceName() {
    try { return localStorage.getItem("nbio.device_name") || ""; } catch (_) { return ""; }
  }

  function showToast(text, ms = 2500) {
    let root = $("#toast-root");
    if (!root) {
      root = document.createElement("div");
      root.id = "toast-root";
      document.body.appendChild(root);
    }
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = text;
    root.appendChild(t);
    setTimeout(() => t.remove(), ms);
  }

  async function submitJson(url, method, payload) {
    try {
      const r = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          "X-Device-Id": getDeviceId(),
        },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error("non-2xx");
      return await r.json();
    } catch (_) {
      showToast("Couldn't save");
      return null;
    }
  }

  // ---------- tabs polyfill ----------

  function wireSettingsTabs() {
    // Native <details name="..."> exclusive-open is supported on
    // Chrome 120+ / Safari 17.4+ / FF 132+. For older browsers, force
    // exclusivity manually on toggle.
    const groups = {};
    $$("details[name]").forEach((d) => {
      const n = d.getAttribute("name");
      (groups[n] = groups[n] || []).push(d);
    });
    Object.values(groups).forEach((members) => {
      if (members.length < 2) return;
      members.forEach((d) => {
        d.addEventListener("toggle", () => {
          if (!d.open) return;
          members.forEach((other) => {
            if (other !== d && other.open) other.open = false;
          });
        });
      });
    });
  }

  // ---------- Baby form ----------

  function wireBabyForm() {
    const form = $("#baby-form");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = new FormData(form);
      const payload = {};
      const name = (data.get("name") || "").trim();
      const dob = (data.get("dob") || "").trim();
      if (name) payload.name = name;
      if (dob) payload.dob = dob;
      const out = await submitJson("/api/babies", "PATCH", payload);
      if (out) showToast("Baby saved");
    });
  }

  // ---------- Device form ----------

  const COLORS = ["#4F8BFF", "#9B6BFF", "#3AB974", "#E08AAE", "#E0A040", "#E25D5D"];

  function wireDeviceForm() {
    const form = $("#device-form");
    if (!form) return;
    const grid = $("#device-color-grid");
    const nameInput = $("#device-name");
    if (!grid || !nameInput) return;
    nameInput.value = getDeviceName();
    let selected = getDeviceColor() || COLORS[0];
    COLORS.forEach((c) => {
      const b = document.createElement("button");
      b.type = "button";
      b.style.background = c;
      b.dataset.color = c;
      b.setAttribute("aria-label", "colour " + c);
      if (c.toLowerCase() === selected.toLowerCase()) b.classList.add("selected");
      b.addEventListener("click", () => {
        selected = c;
        grid.querySelectorAll("button").forEach((x) =>
          x.classList.toggle("selected", x === b)
        );
      });
      grid.appendChild(b);
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const id = getDeviceId();
      if (!id) {
        showToast("No device id — open the app from the home page first");
        return;
      }
      const name = nameInput.value.trim();
      const out = await submitJson(
        "/api/devices/" + encodeURIComponent(id),
        "PUT",
        { name: name || null, color: selected },
      );
      if (out) {
        try {
          localStorage.setItem("nbio.device_color", selected);
          if (name) localStorage.setItem("nbio.device_name", name);
        } catch (_) { /* private mode */ }
        showToast("Device saved");
      }
    });
  }

  // ---------- Theme picker ----------

  function wireThemePicker() {
    const grid = $("#theme-grid");
    if (!grid) return;
    let current;
    try { current = localStorage.getItem("nbio.theme") || "warm"; } catch (_) { current = "warm"; }
    grid.querySelectorAll(".theme-card").forEach((card) => {
      const value = card.dataset.themeValue;
      if (value === current) card.classList.add("selected");
      card.addEventListener("click", () => {
        document.documentElement.dataset.theme = value;
        try { localStorage.setItem("nbio.theme", value); } catch (_) { /* private mode */ }
        grid.querySelectorAll(".theme-card").forEach((c) =>
          c.classList.toggle("selected", c === card)
        );
      });
    });
  }

  // ---------- Server-info readout ----------

  function fmtBytes(n) {
    if (!n) return "0 B";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB";
    return (n / (1024 * 1024 * 1024)).toFixed(2) + " GB";
  }
  function fmtUptime(s) {
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
    if (s < 86400) return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
    return Math.floor(s / 86400) + "d " + Math.floor((s % 86400) / 3600) + "h";
  }

  async function wireServerInfo() {
    const dl = $("#server-info");
    if (!dl) return;
    try {
      const r = await fetch("/api/server-info");
      if (!r.ok) throw new Error("non-2xx");
      const info = await r.json();
      dl.innerHTML =
        "<dt>Version</dt><dd>" + info.version + "</dd>" +
        "<dt>Static-asset hash</dt><dd><code>" + info.static_hash + "</code></dd>" +
        "<dt>DB size</dt><dd>" + fmtBytes(info.db_size_bytes) + "</dd>" +
        "<dt>Uptime</dt><dd>" + fmtUptime(info.uptime_seconds) + "</dd>";
    } catch (_) {
      dl.innerHTML = "<dt>Error</dt><dd>Couldn't load server info</dd>";
    }
  }

  // ---------- Weight form (v1.1.1) ----------

  function uuid() {
    return crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function fmtCommas(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function openWeightModal(todayIso) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal-sheet" role="dialog" aria-modal="true">
        <div class="modal-grab"></div>
        <div class="modal-title">Update weight</div>
        <div class="modal-body">
          <label class="modal-label" for="weight-input">Weight (grams)</label>
          <input id="weight-input" type="number" inputmode="numeric"
                 pattern="[0-9]*" min="1" max="30000" placeholder="e.g. 3420"
                 autocomplete="off">
          <label class="modal-label" for="weight-date" style="margin-top:14px;">Date</label>
          <input id="weight-date" type="date" max="${todayIso}" value="${todayIso}">
          <label class="modal-label" for="weight-notes" style="margin-top:14px;">Notes (optional)</label>
          <input id="weight-notes" type="text" maxlength="500"
                 placeholder="check-up at clinic, etc.">
          <button type="button" class="btn-primary" id="weight-save"
                  style="margin-top:14px;">Save</button>
        </div>
      </div>
    `;
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) backdrop.remove();
    });

    const close = () => backdrop.remove();
    const save = backdrop.querySelector("#weight-save");
    const input = backdrop.querySelector("#weight-input");
    const date = backdrop.querySelector("#weight-date");
    const notes = backdrop.querySelector("#weight-notes");

    save.addEventListener("click", async () => {
      const weight = parseInt(input.value, 10);
      if (!weight || weight < 1 || weight > 30000) {
        showToast("Enter a weight between 1 and 30,000 g");
        return;
      }
      save.disabled = true;
      const payload = {
        measured_at: date.value || todayIso,
        weight_g: weight,
        idempotency_key: "growth-" + uuid(),
        created_by_device: getDeviceId() || "device-anon",
      };
      const n = (notes.value || "").trim();
      if (n) payload.notes = n;
      const out = await submitJson("/api/growth", "POST", payload);
      if (out) {
        showToast("Weight saved");
        close();
        refreshWeightSummary(out.growth);
      } else {
        save.disabled = false;
      }
    });

    document.body.appendChild(backdrop);
    setTimeout(() => input.focus(), 0);
  }

  function refreshWeightSummary(growth) {
    const summary = $("#weight-summary");
    if (!summary || !growth) return;
    const existing = summary.querySelector("[data-weight-latest], [data-weight-empty]");
    const line = document.createElement("p");
    line.className = "weight-latest-line";
    line.dataset.weightLatest = "";
    line.innerHTML =
      `Latest: <b>${fmtCommas(growth.weight_g)} g</b> ` +
      `<span class="muted">· ${growth.measured_at}</span>`;
    if (existing) existing.replaceWith(line);
    else summary.insertBefore(line, summary.querySelector("button"));
    const btn = $("#weight-update-btn");
    if (btn) btn.textContent = "Update weight";
    refreshHeaderWeight(growth.weight_g);
  }

  // Header sticky banner — keep the weight chip in sync with the latest
  // measurement so the user sees the bump without a full reload.
  function refreshHeaderWeight(grams) {
    if (!grams) return;
    let el = document.querySelector("[data-baby-weight]");
    const text = `${fmtCommas(grams)} g`;
    if (el) {
      el.textContent = text;
      return;
    }
    const titleDiv = document.querySelector(".app-header .title");
    if (!titleDiv) return;
    el = document.createElement("span");
    el.className = "baby-weight";
    el.dataset.babyWeight = "";
    el.textContent = text;
    titleDiv.appendChild(el);
  }

  function wireWeightForm() {
    const btn = $("#weight-update-btn");
    if (!btn) return;
    const summary = $("#weight-summary");
    const today = (summary && summary.dataset.today) || new Date().toISOString().slice(0, 10);
    btn.addEventListener("click", () => openWeightModal(today));
  }

  // ---------- init ----------

  document.addEventListener("DOMContentLoaded", () => {
    wireSettingsTabs();
    wireBabyForm();
    wireDeviceForm();
    wireThemePicker();
    wireServerInfo();
    wireWeightForm();
  });
})();
