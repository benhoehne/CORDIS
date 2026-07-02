"""
Data-access layer for the web/export layer (Task 3).
====================================================

All SQLite reads against the consolidated ``heidelberg_projects`` view live
here – the API and the Excel exporter both call these functions so the
filtering logic exists in exactly one place.

The central abstraction is :class:`ProjectFilters`, a plain dataclass that
mirrors the UI controls. :func:`build_where` turns it into a parameterised
``WHERE`` clause (never string-formatted user input → no SQL injection), and
:func:`query_projects` / :func:`fetch_all_filtered` apply it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..db.schema import get_connection, DB_PATH

# Columns returned in the paginated table view (kept lean for the grid).
LIST_COLUMNS = [
    "id", "acronym", "title", "institution", "is_erc",
    "status", "start_year", "end_year",
    "programme_label", "programme_code", "framework_programme",
    "call_identifier", "call_year",
    "erc_pi", "erc_panel", "erc_domain", "erc_grant_type",
    "ec_max_contribution",
]

# Whitelist of sortable columns (protects the ORDER BY clause).
SORTABLE = set(LIST_COLUMNS) | {"total_cost"}



@dataclass
class ProjectFilters:
    """
    Structured representation of the UI filters.

    Every field is optional; unset fields do not constrain the query.
    """
    q: str | None = None                 # free text on title/acronym/keywords
    year_from: int | None = None         # <year_field> >= year_from
    year_to: int | None = None           # <year_field> <= year_to
    year_field: str = "start_year"       # which year column the range applies to
    programme: str | None = None         # matches label / code / framework / call
    programme_label: str | None = None   # exact human-readable programme (dropdown)
    institution: str | None = None       # UHEI | UKHD | UHEI+UKHD
    pi: str | None = None                # ERC researcher (substring)
    panel: str | None = None             # ERC panel (substring)
    erc_only: bool = False               # restrict to is_erc = 1
    status: str | None = None            # e.g. SIGNED / CLOSED

    @classmethod
    def from_query_params(cls, params: dict) -> "ProjectFilters":
        """Build filters from raw query-string values (all strings)."""
        def _int(v):
            try:
                return int(v) if v not in (None, "") else None
            except (ValueError, TypeError):
                return None

        def _str(v):
            v = (v or "").strip()
            return v or None

        # Only allow the two year columns we index; default to start_year.
        yf = _str(params.get("year_field"))
        year_field = yf if yf in ("start_year", "call_year") else "start_year"

        return cls(
            q=_str(params.get("q")),
            year_from=_int(params.get("year_from")),
            year_to=_int(params.get("year_to")),
            year_field=year_field,
            programme=_str(params.get("programme")),
            programme_label=_str(params.get("programme_label")),
            institution=_str(params.get("institution")),
            pi=_str(params.get("pi")),
            panel=_str(params.get("panel")),
            erc_only=str(params.get("erc_only", "")).lower() in ("1", "true", "yes", "on"),
            status=_str(params.get("status")),
        )


def build_where(f: ProjectFilters) -> tuple[str, list]:
    """
    Translate :class:`ProjectFilters` into a parameterised WHERE clause.

    Returns ``(clause, params)`` where *clause* starts with ``WHERE`` (or is an
    empty string when no filters are active) and *params* is the ordered list
    of bound values.
    """
    clauses: list[str] = []
    params: list = []

    if f.q:
        clauses.append(
            "(title LIKE ? OR acronym LIKE ? OR keywords LIKE ? OR objective LIKE ?)"
        )
        like = f"%{f.q}%"
        params += [like, like, like, like]

    # Year range applies to the chosen year column (start_year or call_year).
    year_col = f.year_field if f.year_field in ("start_year", "call_year") else "start_year"
    if f.year_from is not None:
        clauses.append(f"{year_col} >= ?")
        params.append(f.year_from)

    if f.year_to is not None:
        clauses.append(f"{year_col} <= ?")
        params.append(f.year_to)

    if f.programme_label:
        # Exact human-readable programme (dropdown selection).
        clauses.append("programme_label = ?")
        params.append(f.programme_label)

    if f.programme:
        # Free-text programme filter: match the human-readable label, the raw
        # code, the framework or the call identifier.
        clauses.append(
            "(programme_label LIKE ? OR programme_code LIKE ? "
            "OR framework_programme LIKE ? OR call_identifier LIKE ?)"
        )
        like = f"%{f.programme}%"
        params += [like, like, like, like]

    if f.institution:
        clauses.append("institution = ?")
        params.append(f.institution)

    if f.pi:
        clauses.append("erc_pi LIKE ?")
        params.append(f"%{f.pi}%")

    if f.panel:
        clauses.append("erc_panel LIKE ?")
        params.append(f"%{f.panel}%")

    if f.status:
        clauses.append("status = ?")
        params.append(f.status)

    if f.erc_only:
        clauses.append("is_erc = 1")

    clause = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return clause, params


def query_projects(
    filters: ProjectFilters,
    page: int = 1,
    page_size: int = 25,
    sort: str = "start_year",
    direction: str = "desc",
    db_path: str | Path = DB_PATH,
) -> dict:
    """
    Return a page of matching projects plus the total count.

    Output shape::

        {
          "total": <int>,
          "page": <int>,
          "page_size": <int>,
          "pages": <int>,
          "rows": [ {column: value, ...}, ... ]
        }
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    sort = sort if sort in SORTABLE else "start_year"
    direction = "ASC" if str(direction).lower() == "asc" else "DESC"

    where, params = build_where(filters)
    conn = get_connection(db_path)
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM heidelberg_projects {where}", params
        ).fetchone()[0]

        cols = ", ".join(LIST_COLUMNS)
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT {cols}
            FROM heidelberg_projects
            {where}
            ORDER BY {sort} {direction}, id DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
            "rows": [dict(r) for r in rows],
        }
    finally:
        conn.close()


def get_project(project_id: int, db_path: str | Path = DB_PATH) -> dict | None:
    """Return every column of a single project (for the detail view)."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM heidelberg_projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def fetch_all_filtered(
    filters: ProjectFilters, db_path: str | Path = DB_PATH
) -> list[dict]:
    """
    Return **all** columns of **all** matching rows (no pagination).

    Used by the Excel exporter so the download honours exactly the same
    filters as the on-screen table.
    """
    where, params = build_where(filters)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM heidelberg_projects {where} "
            f"ORDER BY start_year DESC, id DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def distinct_values(column: str, db_path: str | Path = DB_PATH) -> list:
    """
    Return the sorted distinct non-null values of a whitelisted column,
    used to populate the UI dropdowns (programme, institution, panel, status).
    """
    allowed = {
        "institution", "status", "programme_label", "programme_code",
        "framework_programme", "erc_panel", "erc_domain", "erc_grant_type",
    }
    if column not in allowed:
        raise ValueError(f"Column not allowed for distinct(): {column}")

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT DISTINCT {column} AS v FROM heidelberg_projects "
            f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY v"
        ).fetchall()
        return [r["v"] for r in rows]
    finally:
        conn.close()
