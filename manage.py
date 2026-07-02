#!/usr/bin/env python3
"""
manage.py — unified CLI for the Heidelberg EU-projects data workflow.
====================================================================

This complements the existing ``run.py`` (which handles live CORDIS API
extraction). ``manage.py`` covers the SQLite database, delta updates and the
web app.

Command groups
--------------
    db build      Build/recreate the SQLite DB from the Excel sources (Task 1)
    db update     Delta-update cordis_projects from a new CORDIS export (Task 2)
    db update-erc Delta-update erc_projects from a new ERC dump (Task 2)
    db export     Build a filtered Excel export from the CLI (Task 3)
    web           Launch the FastAPI web app (Task 3)

Examples
--------
    python manage.py db build --recreate
    python manage.py db update data/cordis_new_export.xlsx
    python manage.py db update-erc data/erc_dump_latest.xlsx
    python manage.py db export --erc-only --year-from 2024 --institution UKHD
    python manage.py web --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).parent))


@click.group()
def cli() -> None:
    """Heidelberg EU-projects management CLI."""


# ── db group ───────────────────────────────────────────────────────────────

@cli.group()
def db() -> None:
    """Database build / update / export commands."""


@db.command("build")
@click.option("--cordis", "cordis_file", default=None,
              help="Path to the CORDIS Excel export (defaults to the bundled one).")
@click.option("--erc", "erc_file", default=None,
              help="Path to the ERC-dashboard dump (defaults to the bundled one).")
@click.option("--recreate", is_flag=True, default=False,
              help="Drop and rebuild all tables from scratch.")
def db_build(cordis_file, erc_file, recreate):
    """Build (or recreate) the consolidated SQLite database (Task 1)."""
    from src.db.build import build_database
    from src.db.load_excel import DEFAULT_CORDIS_FILE, DEFAULT_ERC_FILE
    build_database(
        cordis_file=cordis_file or DEFAULT_CORDIS_FILE,
        erc_file=erc_file or DEFAULT_ERC_FILE,
        recreate=recreate,
    )


@db.command("update")
@click.argument("export_file", type=click.Path(exists=True))
@click.option("--note", default="delta update", help="Note stored in update_log.")
def db_update(export_file, note):
    """Delta-update cordis_projects from a new CORDIS export (Task 2)."""
    from src.etl.update_cordis import update_cordis
    update_cordis(export_file, note=note)


@db.command("update-erc")
@click.argument("dump_file", type=click.Path(exists=True))
@click.option("--heidelberg-only", is_flag=True, default=False,
              help="Keep only ERC rows matching existing CORDIS ids.")
@click.option("--note", default="erc delta update", help="Note stored in update_log.")
def db_update_erc(dump_file, heidelberg_only, note):
    """Delta-update erc_projects from a new ERC dashboard dump (Task 2)."""
    from src.etl.update_erc import update_erc
    update_erc(dump_file, heidelberg_only=heidelberg_only, note=note)


@db.command("export")
@click.option("--q", default=None, help="Free-text search on title/acronym/keywords.")
@click.option("--year-from", type=int, default=None)
@click.option("--year-to", type=int, default=None)
@click.option("--programme", default=None, help="Programme / call substring.")
@click.option("--institution", default=None, help="UHEI | UKHD | UHEI+UKHD.")
@click.option("--pi", default=None, help="ERC researcher substring.")
@click.option("--panel", default=None, help="ERC panel substring.")
@click.option("--erc-only", is_flag=True, default=False)
@click.option("--status", default=None)
def db_export(q, year_from, year_to, programme, institution, pi, panel,
              erc_only, status):
    """Build a filtered Excel export into data/ (same filters as the web UI)."""
    from src.web.repository import ProjectFilters
    from src.web.export import export_filtered
    filters = ProjectFilters(
        q=q, year_from=year_from, year_to=year_to, programme=programme,
        institution=institution, pi=pi, panel=panel, erc_only=erc_only,
        status=status,
    )
    path = export_filtered(filters)
    click.echo(f"✓ Exported → {path}")


# ── web command ────────────────────────────────────────────────────────────

@cli.command("web")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--reload", is_flag=True, default=False, help="Auto-reload (dev).")
def web(host, port, reload):
    """Launch the FastAPI web app (Task 3)."""
    import uvicorn
    uvicorn.run("src.web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
