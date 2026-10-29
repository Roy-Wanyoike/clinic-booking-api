/* Clinic Booking API — live demo frontend (vanilla JS, no build step).
 *
 * Every user action is performed against the real REST API and logged to
 * the on-page API console, so a reviewer can see exactly how each endpoint
 * is consumed: the request, the status code and the JSON envelope.
 *
 * Configuration:
 *   - Default API base is the deployed Render service (below).
 *   - Override with ?api=<base-url> in the address bar, or by defining
 *     window.CLINIC_API_BASE before app.js loads.
 */
"use strict";

const DEFAULT_API_BASE = "https://clinic-booking-api-4k36.onrender.com";
const API_BASE = (() => {
  const fromQuery = new URLSearchParams(location.search).get("api");
  const base = fromQuery || window.CLINIC_API_BASE || DEFAULT_API_BASE;
  return base.replace(/\/+$/, "");
})();

/* All wall-clock times shown and sent to the API are clinic-local
 * (Africa/Nairobi) — see README decision D3. "Tomorrow" must therefore be
 * computed in the clinic's timezone, not the visitor's. */
const NAIROBI_TZ = "Africa/Nairobi";
const DEMO_PATIENT_IDS = [1, 2, 3, 4];

const state = {
  todayISO: null,
  doctors: [],
  doctorId: null,
  date: null,
  slots: [],
  slot: null, // { start_time, end_time } currently selected in step 2
  patients: [], // { id, label }
  managePatientId: null,
  statusFilter: "upcoming",
  appointments: [],
  lastBooking: null, // payload of the last successful booking (409 demo)
};

/* ------------------------------------------------------------------ *
 * Tiny DOM helpers (textContent only — never inject API data as HTML) *
 * ------------------------------------------------------------------ */

const $ = (sel) => document.querySelector(sel);

const dom = {}; // cached element references, filled in cacheDom()

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value);
  }
  for (const child of children) if (child != null) node.append(child);
  return node;
}

const skeleton = (text) => el("div", { class: "skeleton", text });
const emptyBox = (text) => el("p", { class: "empty", text });

/* ------------------------------------------------------------------ *
 * Clinic-time helpers                                                 *
 * ------------------------------------------------------------------ */

function nairobiTodayISO() {
  // "en-CA" formats as YYYY-MM-DD directly.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: NAIROBI_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function addDaysISO(iso, days) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d + days);
  const pad = (n) => String(n).padStart(2, "0");
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`;
}

function prettyDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

const hhmm = (isoDateTime) => isoDateTime.slice(11, 16);

function doctorName(doctorId) {
  const doc = state.doctors.find((d) => d.id === doctorId);
  return doc ? doc.name : `doctor #${doctorId}`;
}

/* ------------------------------------------------------------------ *
 * API console                                                         *
 * ------------------------------------------------------------------ */

let counterTotal = 0;
let counterOk = 0;
let counterErr = 0;

function renderCounters() {
  dom.cTotal.textContent = String(counterTotal);
  dom.cOk.textContent = String(counterOk);
  dom.cErr.textContent = String(counterErr);
}

function logRequest(method, path, body) {
  const statusBadge = el("span", { class: "log-status pending", text: "…" });
  const msSpan = el("span", { class: "log-ms" });
  const head = el(
    "div",
    { class: "log-head", role: "button", tabindex: "0" },
    el("span", { class: `log-method ${method}`, text: method }),
    el("span", { class: "log-path", text: path }),
    statusBadge,
    msSpan
  );
  const bodyWrap = el("div", { class: "log-body", style: "display:none" });
  if (body) {
    bodyWrap.append(
      el("div", { class: "label", text: "Request" }),
      el("pre", { text: JSON.stringify(body, null, 2) })
    );
  }
  const toggle = () => {
    bodyWrap.style.display = bodyWrap.style.display === "none" ? "" : "none";
  };
  head.addEventListener("click", toggle);
  head.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle();
    }
  });

  const item = el("li", { class: "log-item" }, head, bodyWrap);
  dom.consoleList.prepend(item);

  const settle = (cls, label, ms, payload) => {
    statusBadge.className = `log-status ${cls}`;
    statusBadge.textContent = label;
    msSpan.textContent = `${Math.round(ms)} ms`;
    if (payload != null) {
      let text;
      try {
        text = JSON.stringify(payload, null, 2);
      } catch {
        text = String(payload);
      }
      bodyWrap.append(
        el("div", { class: "label", text: `Response ${label}` }),
        el("pre", { text: text.length > 20000 ? text.slice(0, 20000) + " …" : text })
      );
    }
    counterTotal += 1;
    if (typeof label === "number" && label >= 200 && label < 400) counterOk += 1;
    else counterErr += 1;
    renderCounters();
  };

  return {
    complete: (status, ms, data) => {
      const cls = status < 300 ? "s2" : status < 500 ? "s4" : "s5";
      settle(cls, status, ms, data);
    },
    failed: (err, ms) => settle("net", "ERR", ms, { error: String(err) }),
  };
}

async function api(method, path, body) {
  const entry = logRequest(method, path, body ?? null);
  const t0 = performance.now();
  try {
    const resp = await fetch(API_BASE + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(90000), // cold starts can be slow (Render free tier)
    });
    const text = await resp.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    entry.complete(resp.status, performance.now() - t0, data);
    return { ok: resp.ok, status: resp.status, data };
  } catch (err) {
    entry.failed(err, performance.now() - t0);
    return { ok: false, status: 0, data: null };
  }
}

function describeError(result) {
  if (result && result.data && result.data.error) {
    return `${result.data.error.code} — ${result.data.error.message}`;
  }
  if (result && result.status === 0) {
    return "Network error — the API may be cold-starting. Give it a minute and retry.";
  }
  return "Unexpected response — check the console entry for details.";
}

/* ------------------------------------------------------------------ *
 * Toast / banner / pill                                               *
 * ------------------------------------------------------------------ */

let toastTimer;
function toast(message, kind) {
  dom.toast.textContent = message;
  dom.toast.className = "show" + (kind === "err" ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    dom.toast.className = "";
  }, 3500);
}

function setPill(kind, text) {
  dom.healthPill.className = `pill pill-${kind}`;
  dom.healthPill.textContent = text;
}

function showBanner(text) {
  dom.bannerText.textContent = text;
  dom.banner.classList.remove("hidden");
}
function hideBanner() {
  dom.banner.classList.add("hidden");
}

/* ------------------------------------------------------------------ *
 * Step 1 — doctors                                                    *
 * ------------------------------------------------------------------ */

async function loadDoctors() {
  dom.doctorList.replaceChildren(skeleton("Loading doctors from the API…"));
  const r = await api("GET", "/doctors");
  if (!r.ok) {
    dom.doctorList.replaceChildren(emptyBox(describeError(r)));
    return false;
  }
  state.doctors = r.data || [];
  if (!state.doctors.length) {
    dom.doctorList.replaceChildren(emptyBox("The API returned no doctors."));
    return false;
  }
  state.doctorId = state.doctors[0].id;
  renderDoctorCards();
  updateBookSummary();
  return true;
}

function renderDoctorCards() {
  const frag = document.createDocumentFragment();
  for (const doc of state.doctors) {
    const card = el(
      "button",
      {
        class: "doctor-card",
        type: "button",
        "aria-pressed": String(doc.id === state.doctorId),
      },
      el("p", { class: "doctor-name", text: doc.name }),
      el("p", { class: "doctor-spec", text: doc.specialty }),
      el(
        "p",
        { class: "doctor-meta", text: `${doc.working_start.slice(0, 5)}–${doc.working_end.slice(0, 5)} · ${doc.slot_minutes} min slots` }
      )
    );
    card.addEventListener("click", () => selectDoctor(doc.id));
    frag.append(card);
  }
  dom.doctorList.replaceChildren(frag);
}

async function selectDoctor(id) {
  if (state.doctorId === id) return;
  state.doctorId = id;
  state.slot = null;
  renderDoctorCards();
  updateBookSummary();
  await loadAvailability();
}

/* ------------------------------------------------------------------ *
 * Step 2 — availability                                               *
 * ------------------------------------------------------------------ */

async function loadAvailability() {
  if (!state.doctorId) return;
  dom.slotGrid.replaceChildren(skeleton("Loading availability…"));
  const r = await api(
    "GET",
    `/doctors/${state.doctorId}/availability?date=${state.date}`
  );
  if (!r.ok) {
    dom.slotGrid.replaceChildren(emptyBox(describeError(r)));
    return;
  }
  state.slots = (r.data && r.data.available_slots) || [];
  renderSlots();
}

function renderSlots() {
  state.slot = null;
  if (!state.slots.length) {
    dom.slotGrid.replaceChildren(
      emptyBox(
        `No free slots on ${prettyDate(state.date)} — everything is booked, ` +
          "inside the 60-minute lead window, or outside working hours. " +
          "Try another date."
      )
    );
  } else {
    const frag = document.createDocumentFragment();
    for (const slot of state.slots) {
      const chip = el(
        "button",
        {
          class: "slot-chip",
          type: "button",
          "aria-pressed": "false",
        },
        `${hhmm(slot.start_time)} – ${hhmm(slot.end_time)}`
      );
      chip.addEventListener("click", () => {
        state.slot = slot;
        dom.slotGrid
          .querySelectorAll(".slot-chip")
          .forEach((c) => c.setAttribute("aria-pressed", "false"));
        chip.setAttribute("aria-pressed", "true");
        updateBookSummary();
      });
      frag.append(chip);
    }
    dom.slotGrid.replaceChildren(frag);
  }
  updateBookSummary();
}

/* ------------------------------------------------------------------ *
 * Step 3 — booking                                                    *
 * ------------------------------------------------------------------ */

function updateBookSummary() {
  const doc = state.doctors.find((d) => d.id === state.doctorId);
  dom.sumDoctor.textContent = doc
    ? `${doc.name} · ${doc.specialty}`
    : "—";
  dom.sumSlot.textContent = state.slot
    ? `${prettyDate(state.date)} · ${hhmm(state.slot.start_time)}–${hhmm(state.slot.end_time)}`
    : "pick a free slot above";
  dom.bookBtn.disabled = !(doc && state.slot && dom.patientSelect.value);
}

function showBookResult(kind, title, message, extraNode) {
  const box = dom.bookResult;
  box.className = `result-box ${kind === "ok" ? "ok" : "err"}`;
  box.replaceChildren(
    el("p", { class: "err-title", text: title }),
    message ? el("p", { text: message }) : null,
    extraNode || null
  );
  box.classList.remove("hidden");
}

async function bookAppointment() {
  const patientId = Number(dom.patientSelect.value);
  if (!state.doctorId || !state.slot || !patientId) return;
  const payload = {
    doctor_id: state.doctorId,
    patient_id: patientId,
    start_time: state.slot.start_time,
  };

  dom.bookBtn.disabled = true;
  const r = await api("POST", "/appointments", payload);
  dom.bookBtn.disabled = false;
  updateBookSummary();

  if (r.status === 201) {
    state.lastBooking = payload;
    const appt = r.data;
    const retry = el("button", {
      class: "btn small",
      type: "button",
      text: "Book the same slot again — expect 409 SLOT_TAKEN",
    });
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      const r2 = await api("POST", "/appointments", state.lastBooking);
      retry.disabled = false;
      if (r2.status === 409) {
        showBookResult(
          "err",
          `409 · ${r2.data.error.code}`,
          r2.data.error.message +
            " — that is the double-booking guard. The same rule is also " +
            "enforced by a partial unique index at the database level."
        );
      } else if (r2.status === 201) {
        showBookResult("ok", "Booked ✓ (unexpected)", "The slot must have been freed in the meantime.");
      } else {
        showBookResult("err", `${r2.status}`, describeError(r2));
      }
    });
    showBookResult(
      "ok",
      `Booked ✓ — appointment #${appt.id}`,
      `${hhmm(appt.start_time)}–${hhmm(appt.end_time)} on ${prettyDate(appt.start_time.slice(0, 10))} with ${doctorName(appt.doctor_id)}.`,
      retry
    );
    toast("Appointment booked");
    await Promise.all([loadAvailability(), loadAppointments()]);
  } else {
    const code = r.data && r.data.error ? r.data.error.code : String(r.status);
    showBookResult("err", `${r.status || "ERR"} · ${code}`, describeError(r));
  }
}

/* ------------------------------------------------------------------ *
 * Patients (demo scan + registration)                                 *
 * ------------------------------------------------------------------ */

async function scanDemoPatients() {
  const found = [];
  // Sequential on purpose: keeps the console log readable for reviewers.
  for (const id of DEMO_PATIENT_IDS) {
    const r = await api("GET", `/patients/${id}/appointments?status=all`);
    if (r.ok) found.push({ id, label: `Patient #${id} — demo dataset` });
  }
  state.patients = found;
}

function renderPatients(selectedId) {
  for (const select of [dom.patientSelect, dom.managePatientSelect]) {
    select.replaceChildren(
      ...state.patients.map((p) => new Option(p.label, String(p.id)))
    );
  }
  const target = selectedId ?? (state.patients[0] && state.patients[0].id);
  if (target != null) {
    dom.patientSelect.value = String(target);
    dom.managePatientSelect.value = String(target);
    state.managePatientId = target;
  }
  updateBookSummary();
}

async function registerPatient() {
  const name = dom.npName.value.trim();
  const email = dom.npEmail.value.trim();
  const phone = dom.npPhone.value.trim() || null;
  if (!name || !email) {
    toast("Name and email are required to register a patient", "err");
    return;
  }
  dom.npSubmit.disabled = true;
  const r = await api("POST", "/patients", { name, email, phone });
  dom.npSubmit.disabled = false;
  if (r.status === 201) {
    state.patients.push({ id: r.data.id, label: `${r.data.name} (id ${r.data.id})` });
    renderPatients(r.data.id);
    dom.npName.value = "";
    dom.npEmail.value = "";
    dom.npPhone.value = "";
    toast(`Patient #${r.data.id} registered — selected for booking`);
  } else {
    const code = r.data && r.data.error ? r.data.error.code : r.status;
    toast(`Could not register: ${code} — ${r.data && r.data.error ? r.data.error.message : "check the console"}`, "err");
  }
}

/* ------------------------------------------------------------------ *
 * Step 4 — cancel / reschedule                                        *
 * ------------------------------------------------------------------ */

async function loadAppointments() {
  if (!state.managePatientId) {
    dom.apptList.replaceChildren(
      emptyBox("No patients available — register one in step 3 first.")
    );
    return;
  }
  dom.apptList.replaceChildren(skeleton("Loading appointments…"));
  const r = await api(
    "GET",
    `/patients/${state.managePatientId}/appointments?status=${state.statusFilter}`
  );
  if (!r.ok) {
    dom.apptList.replaceChildren(emptyBox(describeError(r)));
    return;
  }
  state.appointments = (r.data && r.data.appointments) || [];
  renderAppointments();
}

function renderAppointments() {
  if (!state.appointments.length) {
    dom.apptList.replaceChildren(
      emptyBox(
        "Nothing here for this filter. Book an appointment in step 3, or switch the status filter."
      )
    );
    return;
  }
  const frag = document.createDocumentFragment();
  for (const appt of state.appointments) frag.append(apptItem(appt));
  dom.apptList.replaceChildren(frag);
}

function apptItem(appt) {
  const item = el("div", {
    class: "appt-item" + (appt.status === "cancelled" ? " cancelled" : ""),
  });
  item.append(
    el(
      "div",
      { class: "appt-top" },
      el(
        "div",
        {},
        el("p", {
          class: "appt-when",
          text: `${prettyDate(appt.start_time.slice(0, 10))} · ${hhmm(appt.start_time)}–${hhmm(appt.end_time)}`,
        }),
        el("p", {
          class: "appt-doc",
          text: `${doctorName(appt.doctor.id)} · ${appt.doctor.specialty}`,
        })
      ),
      el("span", { class: `status-chip ${appt.status}`, text: appt.status })
    )
  );
  if (appt.cancel_reason) {
    item.append(
      el("p", { class: "appt-reason", text: `Reason: ${appt.cancel_reason}` })
    );
  }
  if (appt.status === "booked") {
    const actions = el("div", { class: "appt-actions" });
    const cancelBtn = el("button", {
      class: "btn small ghost-danger",
      type: "button",
      text: "Cancel",
    });
    cancelBtn.addEventListener("click", () => toggleCancelForm(item, appt, cancelBtn));
    const reschedBtn = el("button", {
      class: "btn small",
      type: "button",
      text: "Reschedule",
    });
    reschedBtn.addEventListener("click", () => toggleReschedule(item, appt));
    actions.append(cancelBtn, reschedBtn);
    item.append(actions);
  }
  return item;
}

function closeOpenPanels(item) {
  const existing = item.querySelector(".cancel-form, .reschedule-panel, .appt-error");
  if (existing) existing.remove();
  return existing != null;
}

function showPanelError(item, message) {
  closeOpenPanels(item);
  item.append(el("p", { class: "appt-error", text: message }));
}

function toggleCancelForm(item, appt) {
  const wasOpen = closeOpenPanels(item);
  if (wasOpen) return;

  const input = el("input", {
    type: "text",
    placeholder: "Reason — the API rejects blank reasons",
    "aria-label": "Cancellation reason",
  });
  const confirm = el("button", {
    class: "btn small primary",
    type: "button",
    text: "Confirm cancel",
  });
  const form = el("div", { class: "cancel-form" }, input, confirm);

  confirm.addEventListener("click", async () => {
    const reason = input.value.trim();
    if (!reason) {
      input.focus();
      toast("A cancel reason is required — the API returns 422 for blank reasons", "err");
      return;
    }
    confirm.disabled = true;
    input.disabled = true;
    const r = await api("PATCH", `/appointments/${appt.id}/cancel`, { reason });
    confirm.disabled = false;
    input.disabled = false;
    if (r.ok) {
      form.remove();
      toast(`Cancelled — the ${hhmm(appt.start_time)} slot is free again`);
      await Promise.all([loadAppointments(), loadAvailability()]);
    } else {
      showPanelError(item, describeError(r));
    }
  });

  item.append(form);
  input.focus();
}

function toggleReschedule(item, appt) {
  const wasOpen = closeOpenPanels(item);
  if (wasOpen) return;

  const dateInput = el("input", {
    type: "date",
    min: state.todayISO,
    value: state.date,
    "aria-label": "New date",
  });
  const loadBtn = el("button", { class: "btn small", type: "button", text: "Load free slots" });
  const slotWrap = el("div", { class: "slot-grid" });
  const confirmBtn = el("button", {
    class: "btn small primary",
    type: "button",
    text: "Confirm reschedule",
    disabled: true,
  });
  let chosen = null;

  async function loadSlots() {
    if (!dateInput.value) return;
    slotWrap.replaceChildren(skeleton("Loading slots…"));
    const r = await api(
      "GET",
      `/doctors/${appt.doctor.id}/availability?date=${dateInput.value}`
    );
    if (!r.ok) {
      slotWrap.replaceChildren(emptyBox(describeError(r)));
      return;
    }
    const slots = (r.data && r.data.available_slots) || [];
    if (!slots.length) {
      slotWrap.replaceChildren(emptyBox("No free slots that day — try another date."));
      return;
    }
    slotWrap.replaceChildren(
      ...slots.map((s) => {
        const chip = el(
          "button",
          { class: "slot-chip", type: "button", "aria-pressed": "false" },
          `${hhmm(s.start_time)} – ${hhmm(s.end_time)}`
        );
        chip.addEventListener("click", () => {
          chosen = s;
          confirmBtn.disabled = false;
          slotWrap
            .querySelectorAll(".slot-chip")
            .forEach((c) => c.setAttribute("aria-pressed", "false"));
          chip.setAttribute("aria-pressed", "true");
        });
        return chip;
      })
    );
  }

  loadBtn.addEventListener("click", loadSlots);
  confirmBtn.addEventListener("click", async () => {
    if (!chosen) return;
    confirmBtn.disabled = true;
    const r = await api("PATCH", `/appointments/${appt.id}/reschedule`, {
      start_time: chosen.start_time,
    });
    if (r.ok) {
      item.querySelector(".reschedule-panel")?.remove();
      toast("Appointment rescheduled");
      await Promise.all([loadAppointments(), loadAvailability()]);
    } else {
      confirmBtn.disabled = false;
      showPanelError(item, describeError(r));
    }
  });

  item.append(
    el(
      "div",
      { class: "reschedule-panel" },
      el("div", { class: "avail-bar" }, el("label", { text: "New date" }), dateInput, loadBtn),
      slotWrap,
      confirmBtn
    )
  );
}

/* ------------------------------------------------------------------ *
 * Boot                                                                *
 * ------------------------------------------------------------------ */

function cacheDom() {
  const ids = [
    "banner", "banner-text", "banner-retry", "health-pill", "api-base-link",
    "doctor-list", "date-input", "refresh-slots", "slot-grid",
    "sum-doctor", "sum-slot", "patient-select", "np-name", "np-email",
    "np-phone", "np-submit", "book-btn", "book-result",
    "manage-patient-select", "appt-list", "console-list", "console-clear",
    "c-total", "c-ok", "c-err", "toast",
  ];
  for (const id of ids) dom[id] = document.getElementById(id);
}

async function checkHealth() {
  setPill("pending", "Checking API…");
  const slowTimer = setTimeout(() => {
    showBanner(
      "The API is slow to answer — Render's free tier spins down when idle " +
        "and cold-starts on the first request (can take up to ~60 seconds)."
    );
  }, 4000);
  const r = await api("GET", "/health");
  clearTimeout(slowTimer);
  if (!r.ok) {
    setPill("err", "API unreachable");
    showBanner(
      `Could not reach the API at ${API_BASE}. Check your connection and ` +
        "press “Retry connection”."
    );
    return false;
  }
  hideBanner();
  const clinicTime = r.data && r.data.clinic_time ? r.data.clinic_time.slice(11, 16) : null;
  setPill("ok", clinicTime ? `API live · clinic ${clinicTime}` : "API live");
  return true;
}

async function init() {
  if (!(await checkHealth())) return;
  if (!(await loadDoctors())) return;
  await Promise.all([loadAvailability(), scanDemoPatients()]);
  renderPatients();
  await loadAppointments();
}

function bindEvents() {
  dom.dateInput.min = state.todayISO;
  dom.dateInput.value = state.date;

  dom.dateInput.addEventListener("change", () => {
    if (!dom.dateInput.value) return;
    state.date = dom.dateInput.value;
    loadAvailability();
  });
  dom.refreshSlots.addEventListener("click", () => loadAvailability());
  dom.bookBtn.addEventListener("click", bookAppointment);
  dom.patientSelect.addEventListener("change", updateBookSummary);
  dom.npSubmit.addEventListener("click", registerPatient);
  dom.managePatientSelect.addEventListener("change", () => {
    state.managePatientId = Number(dom.managePatientSelect.value);
    loadAppointments();
  });
  dom.consoleClear.addEventListener("click", () => {
    dom.consoleList.replaceChildren();
    counterTotal = counterOk = counterErr = 0;
    renderCounters();
  });
  dom.bannerRetry.addEventListener("click", () => {
    hideBanner();
    init();
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document
        .querySelectorAll(".tab")
        .forEach((t) => t.setAttribute("aria-pressed", "false"));
      tab.setAttribute("aria-pressed", "true");
      state.statusFilter = tab.dataset.status;
      loadAppointments();
    });
  });
}

cacheDom();
state.todayISO = nairobiTodayISO();
state.date = addDaysISO(state.todayISO, 1);

dom.apiBaseLink.textContent = API_BASE;
dom.apiBaseLink.href = API_BASE + "/docs";
renderCounters();
bindEvents();
init();
