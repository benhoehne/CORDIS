# Heidelberg EU-Projects Database Workflow

A robust, modular workflow that consolidates the two authoritative data
sources into a single SQLite database, supports repeatable delta updates, and
exposes a web + Excel-export layer.

* **CORDIS export** (`data/cordis__20260702_141228.xlsx`) — authoritative base
  of all UHEI/UKHD EU projects since 2014.
* **ERC dashboard dump** (`data/erc_dump_260701.xlsx`) — supplementary ERC
  fields (PI, panel, domain, call year, …).

Join key: `cordis_projects.id  =  erc_projects.project_number`.

---

## 1. Folder structure

```
CORDIS/
├── manage.py                 ← unified CLI (db build / update / export / web)
├── run.py                    ← existing CORDIS API extraction (unchanged)
├── data/
│   ├── cordis__*.xlsx        ← CORDIS export (base)
│   ├── erc_dump_*.xlsx       ← ERC dashboard dump (supplement)
│   └── cordis_heidelberg.db  ← SQLite DB (created by `db build`)
├── src/
│   ├── db/                   ← Task 1 – build the SQLite consolidation
│   │   ├── schema.py         ← connection, column maps, DDL (tables)
│   │   ├── load_excel.py     ← Excel → normalised rows → upsert
│   │   ├── build_views.py    ← heidelberg_projects view + indexes
│   │   └── build.py          ← full-build orchestrator
│   ├── etl/                  ← Task 2 – delta updates
│   │   ├── update_cordis.py  ← stage + upsert a new CORDIS export
│   │   └── update_erc.py     ← upsert a new ERC dump, re-enrich the view
│   └── web/                  ← Task 3 – web + export
│       ├── repository.py     ← data-access layer (all SQLite reads)
│       ├── export.py         ← filtered .xlsx export into data/
│       ├── app.py            ← FastAPI JSON API + static mount
│       └── static/index.html ← single-page frontend (filters/table/detail)
└── docs/DATABASE_WORKFLOW.md ← this file
```

---

## 2. Database schema

### `cordis_projects` (base, PK `id`)
All 43 fields from the CORDIS export, renamed to snake_case
(`totalCost → total_cost`, `ecMaxContribution → ec_max_contribution`, …).
Four **derived** columns are added:

* `start_year`, `end_year` — parsed from the ISO dates (fast range filtering).
* `programme_label` — a concise, human-readable programme name (e.g. "ERC",
  "MSCA", "Health", "European Innovation Council (EIC)") resolved from
  `programme_code` via `src/db/programme.py`. 100 % populated in the sample.
* `call_year` — the call year for **every** project (not just ERC), extracted
  from the first `20xx` in `call_identifier` (e.g. `ERC-2025-COG` → 2025,
  `HORIZON-MSCA-2025-DN-01` → 2025), falling back to the project start year.

The programme mapping (`PROGRAMME_MAP` in `src/db/programme.py`) translates the
machine `programme_code` prefixes of FP7 / H2020 / Horizon Europe into readable
labels and is the single place to review/extend these rules.

### `erc_projects` (supplementary, PK `project_number`)
The 18 ERC-dashboard columns, renamed (`Project Number → project_number`,
`Researcher(s) → researcher`, `Panel → panel`, …). The full EU-wide dump
(~14k rows) is stored; the join naturally restricts the consolidated view to
Heidelberg projects.

### `heidelberg_projects` (consolidated **view**)
`cordis_projects` **LEFT JOIN** `erc_projects` on
`id = project_number`. Every CORDIS project appears exactly once; ERC columns
(`erc_pi`, `erc_panel`, `erc_domain`, …) are `NULL` for non-ERC projects.
Two convenience columns are computed:

* `is_erc` — 1 when an ERC row matched, else 0.
* `institution` — `UHEI` / `UKHD` / `UHEI+UKHD`, derived from `org_names`
  (markers configurable in `build_views.py`).
* `cordis_url` — `https://cordis.europa.eu/project/id/<id>`.

### Housekeeping
* `cordis_staging` — transient landing zone for the delta ETL.
* `update_log` — append-only audit (timestamp, source file, ins/upd counts).

### Indexes
On the base tables (SQLite can't index a view):
`acronym`, `title`, `call_identifier`, `programme_code`,
`framework_programme`, `coordinator_country`, `start_year`, `end_year`,
`status` (CORDIS) and `panel`, `domain`, `grant_type`, `call_year`,
`researcher` (ERC).

---

## 3. Column mapping (review here)

The single source of truth is `src/db/schema.py` — `CORDIS_COLUMNS` and
`ERC_COLUMNS` are lists of `(sql_name, excel_header, sql_type)`. To adjust a
mapping, edit one line there; the loaders, ETL and view all follow.

**Assumptions made** (adjust if your future exports differ):
1. Join key `CORDIS.id == ERC "Project Number"` (96/373 matched in the sample).
2. Dates stored as ISO `YYYY-MM-DD` TEXT → string sort == chronological sort.
3. Monetary fields stored as REAL.
4. Institution classification uses substring markers on `org_names`
   (`RUPRECHT-KARLS-UNIVERSITAET HEIDELBERG`/`UHEI`,
   `UNIVERSITATSKLINIKUM HEIDELBERG`/`UKHD`).
5. Programme labels are derived from `programme_code` prefixes
   (`src/db/programme.py::PROGRAMME_MAP`); `call_year` is parsed from
   `call_identifier`. Review/extend `PROGRAMME_MAP` if new codes appear.

---

## 4. How to run

```bash
pip install -r requirements.txt

# ── Task 1: build (or recreate) the database ──────────────────────────────
python manage.py db build --recreate
#   → data/cordis_heidelberg.db with 373 projects (96 ERC-enriched)

# ── Task 2: delta updates ─────────────────────────────────────────────────
python manage.py db update      data/cordis_new_export.xlsx     # refresh CORDIS
python manage.py db update-erc  data/erc_dump_latest.xlsx       # refresh ERC
#   Idempotent: rerunning the same file inserts 0, updates existing rows,
#   never duplicates. Every run is recorded in update_log.

# ── Task 3: web app ───────────────────────────────────────────────────────
python manage.py web --port 8000        # then open http://127.0.0.1:8000
# or:  uvicorn src.web.app:app --reload

# ── Task 3: CLI export (same filters as the UI) ───────────────────────────
python manage.py db export --erc-only --year-from 2024 --institution UKHD
#   → data/export_erc_2024_ukhd_<timestamp>.xlsx
```

### Delta-update pipeline (Task 2)

```
new CORDIS .xlsx ─► Extract  (read + normalise → cordis_staging)
                 ─► Load     (INSERT … ON CONFLICT(id) DO UPDATE → cordis_projects)
                 ─► Refresh  (rebuild indexes + heidelberg_projects view)
                 ─► Log      (append update_log row)
```

* **No duplicates**: upsert is keyed on the primary key `id`.
* **Changes reflected**: every non-key column is overwritten from the new file.
* **New ERC projects**: a project that first appears via CORDIS lands with
  `is_erc = 0`; the next `db update-erc` enriches it automatically because the
  view join is recomputed on each refresh.

---

## 5. Web / export layer (Task 3)

Clean separation of concerns:

| Layer            | File                     | Responsibility                        |
|------------------|--------------------------|---------------------------------------|
| Data access      | `src/web/repository.py`  | All SQLite reads; `ProjectFilters`    |
| API (JSON)       | `src/web/app.py`         | `/api/projects`, `/api/projects/{id}`, `/api/facets`, `/api/export` |
| Frontend         | `src/web/static/index.html` | Filters, paginated table, detail modal |
| Excel export     | `src/web/export.py`      | Filtered `.xlsx` into `data/`         |

Filters (identical on UI, API and export): year range, programme/call, ERC PI,
institution (UHEI/UKHD), ERC panel, free-text (title/acronym/keywords),
status, ERC-only. The exporter reuses the exact same `ProjectFilters`, so a
download always matches the on-screen result.

---

## 6. Pitfalls & mitigations

* **CORDIS ↔ ERC matching gaps** — some ERC grants may not (yet) be in the
  CORDIS Heidelberg export, and vice-versa. The LEFT JOIN keeps all CORDIS
  projects; unmatched ERC rows simply stay dormant until a matching id appears.
* **Duplicate ERC project numbers** — `normalize_erc` de-dupes on
  `project_number` (last wins).
* **Institution attribution** — based on substring markers in `org_names`; if
  CORDIS changes legal-name spelling, update the markers in `build_views.py`.
* **Date formats** — coerced via `pandas.to_datetime`; unparsable values
  become `NULL` rather than raising.
