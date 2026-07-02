"""
Full-build orchestrator (Task 1).
==================================

Ties the schema / loaders / view together into a single ``build_database``
entry point that:

  1. Opens (and optionally recreates) the SQLite database.
  2. Creates the schema.
  3. Loads the authoritative CORDIS export into ``cordis_projects``.
  4. Loads the supplementary ERC dump into ``erc_projects``.
  5. Builds indexes + the consolidated ``heidelberg_projects`` view.
  6. Records the run in ``update_log``.

Call it from ``run.py`` (``python run.py db build``) or directly:

    from src.db.build import build_database
    build_database(recreate=True)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console

from .schema import get_connection, create_schema, drop_all, DB_PATH
from .load_excel import (
    load_cordis_file,
    load_erc_file,
    DEFAULT_CORDIS_FILE,
    DEFAULT_ERC_FILE,
)
from .build_views import refresh

console = Console()


def _log_run(conn, source_file, table_name, read, inserted, updated, note=""):
    """Append one row to the update_log audit table."""
    conn.execute(
        """
        INSERT INTO update_log
            (run_timestamp, source_file, table_name,
             rows_read, rows_inserted, rows_updated, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            str(source_file),
            table_name,
            read,
            inserted,
            updated,
            note,
        ),
    )
    conn.commit()


def build_database(
    cordis_file: str | Path = DEFAULT_CORDIS_FILE,
    erc_file: str | Path = DEFAULT_ERC_FILE,
    db_path: str | Path = DB_PATH,
    recreate: bool = False,
) -> None:
    """
    Build (or refresh) the consolidated Heidelberg projects database.

    Parameters
    ----------
    cordis_file : path to the authoritative CORDIS Excel export.
    erc_file    : path to the ERC-dashboard Excel dump.
    db_path     : SQLite file to write (default ``data/cordis_heidelberg.db``).
    recreate    : when True, drop everything first for a clean rebuild.
    """
    console.rule("[bold blue]Building Heidelberg projects database[/]")
    console.print(f"[dim]DB:[/]     {db_path}")
    console.print(f"[dim]CORDIS:[/] {cordis_file}")
    console.print(f"[dim]ERC:[/]    {erc_file}")

    conn = get_connection(db_path)
    try:
        if recreate:
            console.print("[yellow]--recreate: dropping existing objects[/]")
            drop_all(conn)

        create_schema(conn)

        # ── Load CORDIS (authoritative base) ─────────────────────────────
        ins, upd = load_cordis_file(conn, cordis_file)
        console.print(
            f"[green]cordis_projects:[/] +{ins} inserted, {upd} updated"
        )
        _log_run(conn, cordis_file, "cordis_projects", ins + upd, ins, upd,
                 note="full build")

        # ── Load ERC (supplementary) ─────────────────────────────────────
        ins_e, upd_e = load_erc_file(conn, erc_file)
        console.print(
            f"[green]erc_projects:[/]    +{ins_e} inserted, {upd_e} updated"
        )
        _log_run(conn, erc_file, "erc_projects", ins_e + upd_e, ins_e, upd_e,
                 note="full build")

        # ── Indexes + consolidated view ──────────────────────────────────
        refresh(conn)
        console.print("[green]✓ Indexes + heidelberg_projects view refreshed[/]")

        # ── Quick sanity summary ─────────────────────────────────────────
        total = conn.execute("SELECT COUNT(*) FROM heidelberg_projects").fetchone()[0]
        erc = conn.execute(
            "SELECT COUNT(*) FROM heidelberg_projects WHERE is_erc = 1"
        ).fetchone()[0]
        console.print(
            f"\n[bold green]Done.[/] {total} projects "
            f"({erc} enriched with ERC data)."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    build_database(recreate=True)
