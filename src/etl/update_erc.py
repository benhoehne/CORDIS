"""
Delta-update ETL for erc_projects (Task 2, ERC side).
=====================================================

Refresh the supplementary ``erc_projects`` table from a newer ERC-dashboard
dump. Because ``erc_projects`` is keyed by ``project_number``, the upsert is
naturally idempotent: rerunning the same dump changes nothing, a newer dump
updates changed fields and inserts new ERC grants.

After the upsert we rebuild the ``heidelberg_projects`` view so that any CORDIS
project whose id now matches a (new) ERC row becomes enriched immediately.

Note on scope
-------------
The raw ERC dump contains *all* ERC grants EU-wide (~14k rows). We keep the
full table because the join to ``cordis_projects`` naturally restricts the
consolidated view to Heidelberg projects only. Storing everything avoids
having to re-filter when new Heidelberg projects appear via CORDIS. If disk
size ever matters, pass ``heidelberg_only=True`` to prune to matched ids.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from rich.console import Console

from ..db.schema import get_connection, create_schema, ERC_COLUMNS, DB_PATH
from ..db.load_excel import normalize_erc, upsert_rows
from ..db.build_views import refresh

console = Console()


def _log_run(conn, source_file, read, inserted, updated, note):
    conn.execute(
        """
        INSERT INTO update_log
            (run_timestamp, source_file, table_name,
             rows_read, rows_inserted, rows_updated, note)
        VALUES (?, ?, 'erc_projects', ?, ?, ?, ?)
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


def update_erc(
    dump_file: str | Path,
    db_path: str | Path = DB_PATH,
    heidelberg_only: bool = False,
    note: str = "erc delta update",
) -> tuple[int, int]:
    """
    Upsert a new ERC-dashboard dump into ``erc_projects`` and refresh the view.

    Parameters
    ----------
    dump_file       : path to the ERC-dashboard ``.xlsx`` export.
    db_path         : SQLite database to update.
    heidelberg_only : when True, keep only ERC rows whose project_number
                      already exists in ``cordis_projects`` (smaller table).
    note            : free-text note stored in ``update_log``.

    Returns
    -------
    (inserted, updated) : counts applied to ``erc_projects``.
    """
    console.rule("[bold blue]ERC delta update[/]")
    console.print(f"[dim]Source:[/] {dump_file}")

    p = Path(dump_file)
    if not p.exists():
        raise FileNotFoundError(f"ERC dump not found: {p}")

    conn = get_connection(db_path)
    try:
        create_schema(conn)
        df = pd.read_excel(p, engine="openpyxl")
        rows = normalize_erc(df)

        if heidelberg_only:
            cordis_ids = {
                r[0] for r in conn.execute("SELECT id FROM cordis_projects")
            }
            rows = [r for r in rows if r["project_number"] in cordis_ids]
            console.print(
                f"[cyan]Filtered to {len(rows)} ERC rows matching CORDIS ids[/]"
            )

        inserted, updated = upsert_rows(
            conn, "erc_projects", ERC_COLUMNS, rows, pk="project_number"
        )
        console.print(
            f"[green]Load:[/] +{inserted} inserted, {updated} updated "
            f"in erc_projects"
        )

        refresh(conn)
        _log_run(conn, dump_file, len(rows), inserted, updated, note)
        console.print("[green]✓ View + indexes refreshed, run logged[/]")

        enriched = conn.execute(
            "SELECT COUNT(*) FROM heidelberg_projects WHERE is_erc = 1"
        ).fetchone()[0]
        console.print(
            f"[bold green]Done.[/] {enriched} Heidelberg projects now carry "
            f"ERC enrichment."
        )
        return inserted, updated
    finally:
        conn.close()
