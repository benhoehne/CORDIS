"""
Delta-update ETL for cordis_projects (Task 2).
==============================================

A repeatable, idempotent pipeline to refresh the database when a new CORDIS
export is available (re-running the Heidelberg query:
``(relations/associations/organization/legalName='UHEI' OR shortName='UHEI'
OR legalName='UKHD' OR shortName='UKHD')``).

Pipeline stages
---------------
Extract   Read the new CORDIS Excel/CSV into a DataFrame and land it verbatim
          (normalised) into the ``cordis_staging`` table.
Transform Normalisation is delegated to ``db.load_excel.normalize_cordis`` so
          the staging rows already match the ``cordis_projects`` schema.
Load      Upsert staging → ``cordis_projects`` by primary key ``id``:
            * new ids are inserted,
            * existing ids have changed fields overwritten,
            * rerunning the same file is a no-op (no duplicates).
Refresh   Rebuild indexes + the consolidated ``heidelberg_projects`` view.
Log       Append an ``update_log`` row (timestamp, file, ins/upd counts).

Why a staging table?
--------------------
Landing raw rows first lets us (a) inspect/validate before touching the
authoritative table, and (b) compute an accurate inserted-vs-updated split by
comparing keys. It is truncated at the start of every run.

New ERC projects
----------------
If a *new* ERC project first appears via CORDIS, it lands in
``cordis_projects`` immediately with ``is_erc = 0`` (no ERC match yet). It is
automatically enriched the next time you refresh ``erc_projects`` with a newer
dashboard dump (``python run.py db update-erc <file>``), because the view join
is recomputed on every refresh.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
from rich.console import Console

from ..db.schema import get_connection, create_schema, CORDIS_COLUMNS, DB_PATH
from ..db.load_excel import normalize_cordis
from ..db.build_views import refresh

console = Console()

_CORDIS_COL_NAMES = [sql for sql, _src, _typ in CORDIS_COLUMNS]


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def _read_export(path: str | Path) -> pd.DataFrame:
    """Read a CORDIS export (``.xlsx`` or ``.csv``) into a DataFrame."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CORDIS export not found: {p}")
    if p.suffix.lower() in {".xlsx", ".xlsm"}:
        return pd.read_excel(p, engine="openpyxl")
    if p.suffix.lower() == ".csv":
        return pd.read_csv(p)
    raise ValueError(f"Unsupported file type: {p.suffix} (use .xlsx or .csv)")


def _load_staging(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Truncate staging and bulk-insert the normalised rows. Returns count."""
    conn.execute("DELETE FROM cordis_staging;")
    col_list = ", ".join(f'"{c}"' for c in _CORDIS_COL_NAMES)
    placeholders = ", ".join("?" for _ in _CORDIS_COL_NAMES)
    sql = f"INSERT INTO cordis_staging ({col_list}) VALUES ({placeholders})"
    conn.executemany(
        sql, [[r.get(c) for c in _CORDIS_COL_NAMES] for r in rows]
    )
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Load (upsert staging -> cordis_projects)
# ---------------------------------------------------------------------------

def _upsert_from_staging(conn: sqlite3.Connection) -> tuple[int, int]:
    """
    Upsert every staging row into ``cordis_projects`` keyed by ``id``.

    Returns ``(inserted, updated)``. The split is computed by first counting
    which staging ids already exist in the target table.
    """
    inserted = conn.execute(
        """
        SELECT COUNT(*) FROM cordis_staging s
        WHERE s.id NOT IN (SELECT id FROM cordis_projects)
        """
    ).fetchone()[0]
    updated = conn.execute(
        """
        SELECT COUNT(*) FROM cordis_staging s
        WHERE s.id IN (SELECT id FROM cordis_projects)
        """
    ).fetchone()[0]

    non_pk = [c for c in _CORDIS_COL_NAMES if c != "id"]
    col_list = ", ".join(f'"{c}"' for c in _CORDIS_COL_NAMES)
    update_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in non_pk)

    conn.execute(
        f"""
        INSERT INTO cordis_projects ({col_list})
        SELECT {col_list} FROM cordis_staging
        WHERE id IS NOT NULL
        ON CONFLICT(id) DO UPDATE SET {update_clause}
        """
    )
    conn.commit()
    return inserted, updated


def _log_run(conn, source_file, read, inserted, updated, note):
    conn.execute(
        """
        INSERT INTO update_log
            (run_timestamp, source_file, table_name,
             rows_read, rows_inserted, rows_updated, note)
        VALUES (?, ?, 'cordis_projects', ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            str(source_file),
            read,
            inserted,
            updated,
            note,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def update_cordis(
    export_file: str | Path,
    db_path: str | Path = DB_PATH,
    note: str = "delta update",
) -> tuple[int, int]:
    """
    Run the full delta-update pipeline for a new CORDIS export.

    Parameters
    ----------
    export_file : path to the freshly-downloaded CORDIS ``.xlsx`` / ``.csv``.
    db_path     : SQLite database to update.
    note        : free-text note stored in ``update_log``.

    Returns
    -------
    (inserted, updated) : counts applied to ``cordis_projects``.
    """
    console.rule("[bold blue]CORDIS delta update[/]")
    console.print(f"[dim]Source:[/] {export_file}")

    conn = get_connection(db_path)
    try:
        create_schema(conn)  # ensure tables exist (safe if already there)

        # Extract + transform
        df = _read_export(export_file)
        rows = normalize_cordis(df)
        n = _load_staging(conn, rows)
        console.print(f"[cyan]Extract:[/] {n} rows staged")

        # Load
        inserted, updated = _upsert_from_staging(conn)
        console.print(
            f"[green]Load:[/] +{inserted} inserted, {updated} updated "
            f"in cordis_projects"
        )

        # Refresh derived objects + audit
        refresh(conn)
        _log_run(conn, export_file, n, inserted, updated, note)
        console.print("[green]✓ View + indexes refreshed, run logged[/]")

        total = conn.execute("SELECT COUNT(*) FROM cordis_projects").fetchone()[0]
        console.print(f"[bold green]Done.[/] cordis_projects now holds {total} rows.")
        return inserted, updated
    finally:
        conn.close()
