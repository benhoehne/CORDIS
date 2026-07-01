#!/usr/bin/env python3
"""
Purge CORDIS Extractions
========================
Lists all extraction tasks stored against your API key and deletes them,
freeing up slots so new extractions can be submitted.

API reference: https://cordis.europa.eu/dataextractions/api-docs
  • listExtractions   GET  /api/dataextractions/listExtractions
  • cancelExtraction  GET  /api/dataextractions/cancelExtraction   (in-progress)
  • deleteExtraction  DEL  /api/dataextractions/deleteExtraction   (all states)

Usage
-----
    python purge_extractions.py                  # interactive confirm
    python purge_extractions.py --yes            # skip confirmation
    python purge_extractions.py --dry-run        # list only, delete nothing
"""

import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent))

from src.cordis_client import CordisClient, CordisAPIError

load_dotenv()
console = Console()


# The CORDIS API spec says "taskID" but real responses may use "taskId" or "id".
_TASK_ID_KEYS = ("taskID", "taskId", "task_id", "id")


def _get_task_id(ex: dict):
    """Return the task ID from an extraction dict, trying all known key names."""
    for key in _TASK_ID_KEYS:
        if key in ex:
            return ex[key]
    return None


def _is_ongoing(ex: dict) -> bool:
    """Return True if the extraction has no result file yet (still running)."""
    return not ex.get("destinationFileUri", "").strip()


@click.command()
@click.option(
    "--key",
    envvar="CORDIS_API_KEY",
    required=True,
    help="CORDIS API key (or set CORDIS_API_KEY env var).",
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt and delete immediately.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List extractions but do not delete anything.",
)
def main(key: str, yes: bool, dry_run: bool):
    """List and delete all CORDIS extraction tasks for the given API key."""
    client = CordisClient(api_key=key)

    # ── List ──────────────────────────────────────────────────────────────────
    console.print("[bold cyan]Fetching extractions…[/]")
    try:
        extractions = client.list_extractions()
    except CordisAPIError as exc:
        console.print(f"[bold red]✗ Failed to list extractions:[/] {exc}")
        sys.exit(1)

    if not extractions:
        console.print("[green]✓ No extractions found – nothing to delete.[/]")
        return

    # ── Display ───────────────────────────────────────────────────────────────
    # Fields per GetExtractionStatusDTO:
    #   taskID, progress, query, numberOfRecords, numberOfProcessedRecords,
    #   numberOfRecordsEstimated, remainingTime, averageSpeed, destinationFileUri
    table = Table(title=f"{len(extractions)} extraction(s) on record", show_lines=True)
    table.add_column("Task ID",  style="bold cyan", no_wrap=True)
    table.add_column("Progress", style="yellow")
    table.add_column("Records",  justify="right")
    table.add_column("File?",    justify="center")
    table.add_column("Query",    style="dim", max_width=60, overflow="fold")

    # Log the raw keys of the first entry if no taskID found (helps diagnose)
    if extractions and _get_task_id(extractions[0]) is None:
        console.print(f"[yellow]⚠ Could not find task ID. Raw keys: {list(extractions[0].keys())}[/]")

    for ex in extractions:
        has_file = "✓" if ex.get("destinationFileUri", "").strip() else "—"
        records  = (
            ex.get("numberOfProcessedRecords")
            or ex.get("numberOfRecords")
            or "?"
        )
        table.add_row(
            str(_get_task_id(ex) or "?"),
            ex.get("progress") or "?",
            str(records),
            has_file,
            ex.get("query") or "?",
        )

    console.print(table)

    if dry_run:
        console.print("[dim]--dry-run set; skipping deletion.[/]")
        return

    # ── Confirm ───────────────────────────────────────────────────────────────
    if not yes:
        click.confirm(
            f"\nDelete all {len(extractions)} extraction(s)?",
            default=False,
            abort=True,
        )

    # ── Delete ────────────────────────────────────────────────────────────────
    deleted = 0
    failed  = 0

    for ex in extractions:
        task_id = _get_task_id(ex)
        if task_id is None:
            console.print(f"[yellow]⚠ Skipping entry – no task ID found. Keys: {list(ex.keys())}[/]")
            continue

        # Cancel first if the task is still running
        if _is_ongoing(ex):
            try:
                client.cancel_extraction(task_id)
                console.print(f"[dim]  Cancelled in-progress task {task_id}[/]")
            except CordisAPIError as exc:
                console.print(f"[yellow]⚠ Could not cancel task {task_id} (proceeding to delete anyway):[/] {exc}")

        try:
            client.delete_extraction(task_id)
            console.print(f"[green]✓ Deleted task {task_id}[/]")
            deleted += 1
        except CordisAPIError as exc:
            console.print(f"[red]✗ Could not delete task {task_id}:[/] {exc}")
            failed += 1

    console.print(
        f"\n[bold]Done.[/] Deleted [green]{deleted}[/] extraction(s)"
        + (f", [red]{failed} failed[/]." if failed else ".")
    )


if __name__ == "__main__":
    main()
