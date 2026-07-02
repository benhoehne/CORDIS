// ── Server mode bootstrap ─────────────────────────────────────────────────────
// Hide the loading screen immediately (only needed in standalone/sql.js mode).
document.getElementById("loading-screen").style.display = "none";

// ── App state ─────────────────────────────────────────────────────────────────
const state = { page: 1, sort: "start_year", direction: "desc" };

// ── Helpers ───────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const money = (v) => v == null ? "" :
  "€" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
const esc = (s) => (s == null ? "" : String(s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"));

// ── Multi-select dropdown ─────────────────────────────────────────────────────
const progState = { selected: new Set(), allOptions: [] };

function initProgDropdown() {
  const trigger  = $("prog-trigger");
  const panel    = $("prog-panel");
  const chevron  = $("prog-chevron");
  const search   = $("prog-search");
  const clearBtn = $("prog-clear");
  const closeBtn = $("prog-close");

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = !panel.classList.contains("hidden");
    panel.classList.toggle("hidden");
    chevron.classList.toggle("rotate-180");
    if (!isOpen) search.focus();
  });

  search.addEventListener("input", () =>
    renderProgOptions(search.value.trim().toLowerCase())
  );

  clearBtn.addEventListener("click", () => {
    progState.selected.clear();
    renderProgOptions(search.value.trim().toLowerCase());
    updateProgTrigger();
    syncHiddenSelect();
  });

  closeBtn.addEventListener("click", () => {
    panel.classList.add("hidden");
    chevron.classList.remove("rotate-180");
  });

  document.addEventListener("click", (e) => {
    if (!$("prog-wrapper").contains(e.target)) {
      panel.classList.add("hidden");
      chevron.classList.remove("rotate-180");
    }
  });
}

function renderProgOptions(filter = "") {
  const list = $("prog-list");
  list.innerHTML = "";
  const groups = {};
  for (const item of progState.allOptions) {
    if (filter && !item.value.toLowerCase().includes(filter)) continue;
    const g = item.group || "Other";
    if (!groups[g]) groups[g] = [];
    groups[g].push(item);
  }

  for (const [groupName, items] of Object.entries(groups)) {
    const li = document.createElement("li");
    li.className = "px-3 py-1 text-xs font-semibold text-gray-400 uppercase tracking-wide mt-1 select-none";
    li.textContent = groupName;
    list.appendChild(li);

    for (const item of items) {
      const opt = document.createElement("li");
      const checked = progState.selected.has(item.value);
      opt.className =
        `flex items-center gap-2.5 px-3 py-1.5 cursor-pointer text-sm hover:bg-gray-50 ` +
        (checked ? "text-uhei" : "text-gray-700");
      opt.innerHTML = `
        <span class="w-4 h-4 shrink-0 rounded border flex items-center justify-center text-white text-xs
          ${checked ? "bg-uhei border-uhei" : "border-gray-300 bg-white"}">
          ${checked ? "✓" : ""}
        </span>
        <span class="truncate">${esc(item.label)}</span>`;
      opt.addEventListener("click", () => {
        progState.selected.has(item.value)
          ? progState.selected.delete(item.value)
          : progState.selected.add(item.value);
        renderProgOptions(filter);
        updateProgTrigger();
        syncHiddenSelect();
      });
      list.appendChild(opt);
    }
  }

  if (!list.children.length) {
    const li = document.createElement("li");
    li.className = "px-3 py-3 text-sm text-gray-400 text-center";
    li.textContent = "No programmes found.";
    list.appendChild(li);
  }
}

function updateProgTrigger() {
  const display = $("prog-display");
  const count = progState.selected.size;
  if (count === 0) {
    display.textContent = "All programmes";
    display.className = "truncate text-gray-400";
  } else if (count === 1) {
    const val = [...progState.selected][0];
    display.textContent = val.length > 42 ? val.slice(0, 39) + "…" : val;
    display.className = "truncate text-gray-800";
  } else {
    display.textContent = `${count} programmes selected`;
    display.className = "truncate text-gray-800 font-medium";
  }
}

function syncHiddenSelect() {
  const sel = $("f-programme-label");
  for (const opt of sel.options) {
    opt.selected = progState.selected.has(opt.value);
  }
}

// ── Filters ───────────────────────────────────────────────────────────────────
function currentFilters() {
  return {
    q: $("f-q").value,
    year_field: $("f-year-field").value,
    year_from: $("f-year-from").value,
    year_to: $("f-year-to").value,
    programme_label: Array.from(progState.selected),
    programme: $("f-programme").value,
    institution: $("f-institution").value,
    status: $("f-status").value,
    pi: $("f-pi").value,
    panel: $("f-panel").value,
    erc_only: $("f-erc-only").checked ? "1" : "",
  };
}

function buildQuery(extra = {}) {
  const params = new URLSearchParams();
  const f = currentFilters();
  for (const [k, v] of Object.entries(f)) {
    if (Array.isArray(v)) {
      for (const item of v) if (item) params.append(k, item);
    } else if (v) {
      params.set(k, v);
    }
  }
  for (const [k, v] of Object.entries(extra)) if (v != null) params.set(k, v);
  return params.toString();
}

// ── Facets ────────────────────────────────────────────────────────────────────
async function loadFacets() {
  const r = await fetch("/api/facets");
  const f = await r.json();
  fill("f-institution", f.institution);
  fill("f-status", f.status);
  fill("f-panel", f.erc_panel);
  fillProgramme(f.programme_label);
}

function fill(id, values) {
  const sel = $(id);
  for (const v of values) {
    const o = document.createElement("option");
    o.value = v; o.textContent = v.length > 60 ? v.slice(0, 57) + "…" : v;
    sel.appendChild(o);
  }
}

function fillProgramme(values) {
  const erc  = values.filter(v => v === "ERC" || v.startsWith("ERC "));
  const msca = values.filter(v => v === "MSCA" || v.startsWith("MSCA "));
  const rest = values.filter(v => !v.startsWith("ERC") && !v.startsWith("MSCA"));
  const toItem = (v, group) => ({
    value: v, label: v.length > 55 ? v.slice(0, 52) + "…" : v, group
  });
  progState.allOptions = [
    ...erc.map(v  => toItem(v, "ERC")),
    ...msca.map(v => toItem(v, "MSCA")),
    ...rest.map(v => toItem(v, "Other")),
  ];
  const sel = $("f-programme-label");
  for (const item of progState.allOptions) {
    const o = document.createElement("option");
    o.value = item.value; o.textContent = item.label;
    sel.appendChild(o);
  }
  renderProgOptions();
}

// ── Load table ────────────────────────────────────────────────────────────────
async function load() {
  const qs = buildQuery({
    page: state.page,
    page_size: $("page-size").value,
    sort: state.sort,
    direction: state.direction,
  });
  const r = await fetch("/api/projects?" + qs);
  const data = await r.json();
  render(data);
}

function render(data) {
  const tbody = $("rows");
  tbody.innerHTML = "";
  $("empty").classList.toggle("hidden", data.rows.length > 0);
  $("empty").classList.toggle("block",  data.rows.length === 0);

  for (const p of data.rows) {
    const tr = document.createElement("tr");
    tr.onclick = () => openDetail(p.id);
    tr.className = "hover:bg-gray-50 cursor-pointer border-b border-gray-100 last:border-0";
    tr.innerHTML = `
      <td class="px-3 py-2 text-sm align-top">${p.id}</td>
      <td class="px-3 py-2 text-sm align-top font-semibold">${esc(p.acronym)}</td>
      <td class="px-3 py-2 text-sm align-top">${esc((p.title || "").slice(0, 90))}</td>
      <td class="px-3 py-2 text-sm align-top">${p.institution
        ? `<span class="chip-inst">${esc(p.institution)}</span>` : ""}</td>
      <td class="px-3 py-2 text-sm align-top">${p.is_erc
        ? `<span class="chip-erc">ERC</span>` : ""}</td>
      <td class="px-3 py-2 text-sm align-top">${p.start_year ?? ""}</td>
      <td class="px-3 py-2 text-sm align-top">${p.call_year ?? ""}</td>
      <td class="px-3 py-2 text-sm align-top" title="${esc(p.programme_code || "")}">
        ${esc(p.programme_label || p.framework_programme || "")}</td>
      <td class="px-3 py-2 text-sm align-top">${esc(p.erc_pi || "")}</td>
      <td class="px-3 py-2 text-sm align-top">${esc((p.erc_panel || "").split(" - ")[0])}</td>
      <td class="px-3 py-2 text-sm align-top text-right tabular-nums">${money(p.ec_max_contribution)}</td>`;
    tbody.appendChild(tr);
  }

  $("count").textContent =
    `${data.total.toLocaleString()} project(s) · sorted by ${state.sort} ${state.direction}`;
  $("page-info").textContent = `Page ${data.page} / ${data.pages || 1}`;
  $("prev").disabled = data.page <= 1;
  $("next").disabled = data.page >= data.pages;
}

// ── Detail modal ──────────────────────────────────────────────────────────────
async function openDetail(id) {
  const r = await fetch("/api/projects/" + id);
  if (!r.ok) return;
  const p = await r.json();
  $("d-title").textContent = p.title || "(untitled)";
  $("d-acr").textContent =
    `${p.acronym || ""} · ID ${p.id}` + (p.is_erc ? " · ERC" : "");
  const fields = [
    ["Institution",         p.institution],
    ["Status",              p.status],
    ["Coordinator",         p.coordinator_name],
    ["Start / End",         `${p.start_date || ""} → ${p.end_date || ""}`],
    ["Duration (mo.)",      p.duration],
    ["Programme",           p.programme_label],
    ["Framework",           p.framework_programme],
    ["Programme code",      p.programme_code],
    ["Call",                p.call_identifier],
    ["Call year",           p.call_year],
    ["Topic",               p.topic_title],
    ["Total cost",          money(p.total_cost)],
    ["EC contribution",     money(p.ec_max_contribution)],
    ["ERC PI",              p.erc_pi],
    ["ERC panel",           p.erc_panel],
    ["ERC domain",          p.erc_domain],
    ["ERC grant type",      p.erc_grant_type],
    ["ERC call year",       p.erc_call_year],
    ["ERC EU contribution", money(p.erc_eu_contribution)],
    ["Organisations",       p.org_names],
    ["Objective",           p.objective],
    ["CORDIS", p.cordis_url
      ? `<a href="${p.cordis_url}" target="_blank" class="text-uhei hover:underline">${p.cordis_url}</a>`
      : ""],
  ];
  $("d-body").innerHTML = fields
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) =>
      `<dt class="text-gray-500">${k}</dt>` +
      `<dd class="break-words">${k === "CORDIS" ? v : esc(v)}</dd>`
    ).join("");
  const overlay = $("overlay");
  overlay.classList.remove("hidden");
  overlay.classList.add("flex");
}

function closeDetail() {
  $("overlay").classList.add("hidden");
  $("overlay").classList.remove("flex");
}

// ── Controls ──────────────────────────────────────────────────────────────────
function applyFilters() { state.page = 1; load(); }
function gotoPage(p) { if (p >= 1) { state.page = p; load(); } }

function setSort(col) {
  if (state.sort === col)
    state.direction = state.direction === "asc" ? "desc" : "asc";
  else { state.sort = col; state.direction = "desc"; }
  load();
}

function resetFilters() {
  for (const el of document.querySelectorAll(".filters input"))
    el.type === "checkbox" ? (el.checked = false) : (el.value = "");
  for (const el of document.querySelectorAll(".filters select"))
    if (!el.multiple) el.value = "";
  progState.selected.clear();
  renderProgOptions();
  updateProgTrigger();
  syncHiddenSelect();
  applyFilters();
}

function exportXlsx() {
  window.location = "/api/export?" + buildQuery();
}

// ── Init ──────────────────────────────────────────────────────────────────────
initProgDropdown();
loadFacets().then(load);
$("f-q").addEventListener("keydown", (e) => { if (e.key === "Enter") applyFilters(); });
