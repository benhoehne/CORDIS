// ── Configuration ─────────────────────────────────────────────────────────────
// Path to the SQLite database file, relative to the HTML page.
const DB_URL = "cordis_heidelberg.db";

// ── App state ─────────────────────────────────────────────────────────────────
const state = { page: 1, sort: "start_year", direction: "desc" };
let db = null;   // sql.js Database instance, set after load

// ── Helpers ───────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const money = (v) => v == null ? "" :
  "€" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
const esc = (s) => (s == null ? "" : String(s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"));

// ── Column lists (mirrors repository.py LIST_COLUMNS) ─────────────────────────
const LIST_COLUMNS = [
  "id", "acronym", "title", "institution", "is_erc",
  "status", "start_year", "end_year",
  "programme_label", "programme_code", "framework_programme",
  "call_identifier", "call_year",
  "erc_pi", "erc_panel", "erc_domain", "erc_grant_type",
  "ec_max_contribution",
];
const SORTABLE = new Set([...LIST_COLUMNS, "total_cost"]);

// ── sql.js query helpers ───────────────────────────────────────────────────────
/**
 * Run a SELECT and return an array of plain objects.
 * sql.js exec() returns [{columns:[...], values:[[...],...]}, ...]
 */
function runQuery(sql, params = []) {
  const results = db.exec(sql, params);
  if (!results.length) return [];
  const { columns, values } = results[0];
  return values.map(row =>
    Object.fromEntries(columns.map((c, i) => [c, row[i]]))
  );
}

function runScalar(sql, params = []) {
  const r = db.exec(sql, params);
  return r.length && r[0].values.length ? r[0].values[0][0] : null;
}

// ── WHERE clause builder (mirrors build_where in repository.py) ────────────────
function buildWhere(f) {
  const clauses = [];
  const params  = [];

  if (f.q) {
    clauses.push(
      "(title LIKE ? OR acronym LIKE ? OR keywords LIKE ? OR objective LIKE ?)"
    );
    const like = `%${f.q}%`;
    params.push(like, like, like, like);
  }

  const yearCol = f.year_field === "call_year" ? "call_year" : "start_year";
  if (f.year_from) { clauses.push(`${yearCol} >= ?`); params.push(+f.year_from); }
  if (f.year_to)   { clauses.push(`${yearCol} <= ?`); params.push(+f.year_to);   }

  if (f.programme_labels && f.programme_labels.length) {
    const ph = f.programme_labels.map(() => "?").join(", ");
    clauses.push(`programme_label IN (${ph})`);
    params.push(...f.programme_labels);
  }

  if (f.programme) {
    clauses.push(
      "(programme_label LIKE ? OR programme_code LIKE ? " +
      "OR framework_programme LIKE ? OR call_identifier LIKE ?)"
    );
    const like = `%${f.programme}%`;
    params.push(like, like, like, like);
  }

  if (f.institution) { clauses.push("institution = ?");  params.push(f.institution); }
  if (f.pi)          { clauses.push("erc_pi LIKE ?");    params.push(`%${f.pi}%`); }
  if (f.panel)       { clauses.push("erc_panel LIKE ?"); params.push(`%${f.panel}%`); }
  if (f.status)      { clauses.push("status = ?");       params.push(f.status); }
  if (f.erc_only)    clauses.push("is_erc = 1");

  const where = clauses.length ? "WHERE " + clauses.join(" AND ") : "";
  return [where, params];
}

function currentFilters() {
  return {
    q: $("f-q").value.trim(),
    year_field: $("f-year-field").value,
    year_from: $("f-year-from").value,
    year_to: $("f-year-to").value,
    programme_labels: [...progState.selected],
    programme: $("f-programme").value.trim(),
    institution: $("f-institution").value,
    status: $("f-status").value,
    pi: $("f-pi").value.trim(),
    panel: $("f-panel").value,
    erc_only: $("f-erc-only").checked,
  };
}

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
    const opening = panel.classList.contains("hidden");
    panel.classList.toggle("hidden");
    chevron.classList.toggle("rotate-180");
    if (opening) search.focus();
  });

  search.addEventListener("input", () =>
    renderProgOptions(search.value.trim().toLowerCase())
  );

  clearBtn.addEventListener("click", () => {
    progState.selected.clear();
    renderProgOptions($("prog-search").value.trim().toLowerCase());
    updateProgTrigger();
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
    const g = item.group;
    if (!groups[g]) groups[g] = [];
    groups[g].push(item);
  }

  for (const [groupName, items] of Object.entries(groups)) {
    const header = document.createElement("li");
    header.className = "px-3 py-1 text-xs font-semibold text-gray-400 uppercase tracking-wide mt-1 select-none";
    header.textContent = groupName;
    list.appendChild(header);

    for (const item of items) {
      const li = document.createElement("li");
      const checked = progState.selected.has(item.value);
      li.className =
        `flex items-center gap-2.5 px-3 py-1.5 cursor-pointer text-sm hover:bg-gray-50 ` +
        (checked ? "text-uhei" : "text-gray-700");
      li.innerHTML = `
        <span class="w-4 h-4 shrink-0 rounded border flex items-center justify-center text-white text-xs
          ${checked ? "bg-uhei border-uhei" : "border-gray-300 bg-white"}">
          ${checked ? "✓" : ""}
        </span>
        <span class="truncate">${esc(item.label)}</span>`;
      li.addEventListener("click", () => {
        progState.selected.has(item.value)
          ? progState.selected.delete(item.value)
          : progState.selected.add(item.value);
        renderProgOptions(filter);
        updateProgTrigger();
      });
      list.appendChild(li);
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
  const n = progState.selected.size;
  if (n === 0) {
    display.textContent = "All programmes";
    display.className = "truncate text-gray-400";
  } else if (n === 1) {
    const v = [...progState.selected][0];
    display.textContent = v.length > 42 ? v.slice(0, 39) + "…" : v;
    display.className = "truncate text-gray-800";
  } else {
    display.textContent = `${n} programmes selected`;
    display.className = "truncate text-gray-800 font-medium";
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
  renderProgOptions();
}

// ── Facets ────────────────────────────────────────────────────────────────────
function loadFacets() {
  const distinct = (col) => runQuery(
    `SELECT DISTINCT ${col} AS v FROM heidelberg_projects
     WHERE ${col} IS NOT NULL AND ${col} != '' ORDER BY v`
  ).map(r => r.v);

  fill("f-institution", distinct("institution"));
  fill("f-status",      distinct("status"));
  fill("f-panel",       distinct("erc_panel"));
  fillProgramme(distinct("programme_label"));
}

function fill(id, values) {
  const sel = $(id);
  for (const v of values) {
    const o = document.createElement("option");
    o.value = v;
    o.textContent = v.length > 60 ? v.slice(0, 57) + "…" : v;
    sel.appendChild(o);
  }
}

// ── Load table ────────────────────────────────────────────────────────────────
function load() {
  const f = currentFilters();
  const pageSize = +$("page-size").value || 25;
  const page     = Math.max(1, state.page);
  const sort     = SORTABLE.has(state.sort) ? state.sort : "start_year";
  const dir      = state.direction === "asc" ? "ASC" : "DESC";

  const [where, params] = buildWhere(f);
  const cols   = LIST_COLUMNS.join(", ");
  const offset = (page - 1) * pageSize;

  const total = runScalar(
    `SELECT COUNT(*) FROM heidelberg_projects ${where}`, params
  ) || 0;

  const rows = runQuery(
    `SELECT ${cols} FROM heidelberg_projects ${where}
     ORDER BY ${sort} ${dir}, id DESC
     LIMIT ? OFFSET ?`,
    [...params, pageSize, offset]
  );

  const pages = Math.max(1, Math.ceil(total / pageSize));
  render({ total, page, pages, rows });
}

function render({ total, page, pages, rows }) {
  const tbody = $("rows");
  tbody.innerHTML = "";
  $("empty").classList.toggle("hidden", rows.length > 0);
  $("empty").classList.toggle("block",  rows.length === 0);

  for (const p of rows) {
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
    `${total.toLocaleString()} project(s) · sorted by ${state.sort} ${state.direction}`;
  $("page-info").textContent = `Page ${page} / ${pages}`;
  $("prev").disabled = page <= 1;
  $("next").disabled = page >= pages;
}

// ── Detail modal ──────────────────────────────────────────────────────────────
function openDetail(id) {
  const rows = runQuery(
    "SELECT * FROM heidelberg_projects WHERE id = ?", [id]
  );
  if (!rows.length) return;
  const p = rows[0];

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
      `<dd class="break-words">${k === "CORDIS" ? v : esc(String(v))}</dd>`
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
  applyFilters();
}

// ── xlsx export (client-side via SheetJS) ─────────────────────────────────────
function exportXlsx() {
  const f = currentFilters();
  const [where, params] = buildWhere(f);
  const rows = runQuery(
    `SELECT * FROM heidelberg_projects ${where}
     ORDER BY start_year DESC, id DESC`,
    params
  );

  if (!rows.length) { alert("No rows to export."); return; }

  const ws = XLSX.utils.json_to_sheet(rows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Projects");

  const stamp = new Date().toISOString().slice(0, 10);
  XLSX.writeFile(wb, `heidelberg_projects_${stamp}.xlsx`);
}

// ── Bootstrap: load sql.js + fetch the database ───────────────────────────────
async function init() {
  const loadMsg = $("loading-msg");
  try {
    loadMsg.textContent = "Initialising SQLite engine…";
    const SQL = await initSqlJs({
      locateFile: (file) =>
        `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/${file}`,
    });

    loadMsg.textContent = "Fetching database…";
    const response = await fetch(DB_URL);
    if (!response.ok)
      throw new Error(`Cannot fetch database: ${response.status} ${response.statusText}`);

    const buffer = await response.arrayBuffer();
    db = new SQL.Database(new Uint8Array(buffer));

    // Hide loader
    $("loading-screen").style.display = "none";

    // Wire up UI
    initProgDropdown();
    loadFacets();
    load();

    $("f-q").addEventListener("keydown", (e) => {
      if (e.key === "Enter") applyFilters();
    });

  } catch (err) {
    loadMsg.textContent = `Error: ${err.message}`;
    loadMsg.className = "text-sm text-red-600 font-semibold max-w-sm text-center px-4";
    console.error(err);
  }
}

init();
