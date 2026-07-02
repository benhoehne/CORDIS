"""
Excel → SQLite loaders for the Heidelberg EU-projects database.
===============================================================

Responsibilities
----------------
* Read the two authoritative Excel exports into pandas DataFrames.
* Normalise them onto the SQL column layout defined in ``schema.py``
  (rename headers, coerce dates/numbers, derive ``start_year`` / ``end_year``).
* Bulk-load them into ``cordis_projects`` / ``erc_projects``.

The same normalisation helpers are re-used by the delta-update ETL
(``src/etl/update_cordis.py``) so that a full rebuild and an incremental
refresh produce byte-for-byte identical rows.

Every value written is a plain Python scalar (str/int/float/None) – never a
numpy/pandas NA – so that SQLite stores clean NULLs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .schema import (
    CORDIS_COLUMNS,
    ERC_COLUMNS,
    CORDIS_SOURCE_TO_SQL,
    ERC_SOURCE_TO_SQL,
)
from .programme import derive_programme_label, derive_call_year


# Default source locations (can be overridden by the caller / CLI).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CORDIS_FILE = DATA_DIR / "cordis__20260702_141228.xlsx"
DEFAULT_ERC_FILE = DATA_DIR / "erc_dump_260701.xlsx"


# ---------------------------------------------------------------------------
# Low-level normalisation helpers
# ---------------------------------------------------------------------------

def _to_iso_date(value) -> str | None:
    """
    Coerce any date-ish value to an ISO ``YYYY-MM-DD`` string, or None.

    Handles CORDIS strings (``2014-07-01``), ERC datetimes
    (``2026-02-01 00:00:00``) and native datetime/Timestamp objects.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _year_from_iso(iso_date: str | None) -> int | None:
    """Return the 4-digit year from an ISO date string, else None."""
    if not iso_date:
        return None
    try:
        return int(iso_date[:4])
    except (ValueError, TypeError):
        return None


def _clean_scalar(value, sql_type: str):
    """
    Convert a single DataFrame cell into a SQLite-friendly Python scalar.

    * pandas NA / NaN / NaT  -> None
    * INTEGER columns        -> int (or None)
    * REAL columns           -> float (or None)
    * TEXT columns           -> str (or None), stripped
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if pd.isna(value):  # catches NaT / <NA>
            return None
    except (TypeError, ValueError):
        pass

    if sql_type == "INTEGER":
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    if sql_type == "REAL":
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    # TEXT
    text = str(value).strip()
    return text if text != "" else None


# ---------------------------------------------------------------------------
# DataFrame → list[dict] normalisers
# ---------------------------------------------------------------------------

def normalize_cordis(df: pd.DataFrame) -> list[dict]:
    """
    Map a raw CORDIS export DataFrame onto the ``cordis_projects`` schema.

    Returns a list of dicts keyed by SQL column name, ready for
    :func:`upsert_rows`. Unknown source columns are ignored; missing ones
    become None. ``start_year`` / ``end_year`` are derived from the dates.
    """
    type_by_sql = {sql: typ for sql, _src, typ in CORDIS_COLUMNS}
    date_cols = {"start_date", "end_date"}

    records: list[dict] = []
    for _, row in df.iterrows():
        rec: dict = {}
        for sql_name, src, sql_type in CORDIS_COLUMNS:
            if src is None:
                continue  # derived, handled below
            raw = row[src] if src in df.columns else None
            if sql_name in date_cols:
                rec[sql_name] = _to_iso_date(raw)
            else:
                rec[sql_name] = _clean_scalar(raw, sql_type)

        # Derived: project start/end years
        rec["start_year"] = _year_from_iso(rec.get("start_date"))
        rec["end_year"] = _year_from_iso(rec.get("end_date"))

        # Derived: human-readable programme label + call year (all projects).
        # See src/db/programme.py for the mapping rules.
        rec["programme_label"] = derive_programme_label(
            rec.get("programme_code"),
            rec.get("call_identifier"),
            rec.get("programme_title"),
        )
        rec["call_year"] = derive_call_year(
            rec.get("call_identifier"),
            rec.get("start_date"),
        )
        records.append(rec)
    return records


def normalize_erc(df: pd.DataFrame) -> list[dict]:
    """
    Map a raw ERC-dashboard export DataFrame onto the ``erc_projects`` schema.

    ERC rows without a numeric ``Project Number`` are dropped (they cannot be
    joined to CORDIS). Duplicate project numbers keep the *last* occurrence.
    """
    date_cols = {"start_date", "end_date"}
    seen: dict[int, dict] = {}

    for _, row in df.iterrows():
        rec: dict = {}
        for sql_name, src, sql_type in ERC_COLUMNS:
            raw = row[src] if src in df.columns else None
            if sql_name in date_cols:
                rec[sql_name] = _to_iso_date(raw)
            else:
                rec[sql_name] = _clean_scalar(raw, sql_type)

        pn = rec.get("project_number")
        if pn is None:
            continue  # cannot join without a key
        seen[pn] = rec  # dedupe on project_number, last wins

    return list(seen.values())


# ---------------------------------------------------------------------------
# Generic upsert
# ---------------------------------------------------------------------------

def upsert_rows(
    conn: sqlite3.Connection,
    table: str,
    columns: list[tuple[str, str | None, str]],
    rows: list[dict],
    pk: str,
) -> tuple[int, int]:
    """
    Upsert *rows* into *table* keyed by *pk*.

    Uses SQLite ``INSERT … ON CONFLICT(pk) DO UPDATE`` so that:
      * new keys are inserted,
      * existing keys have their non-key columns overwritten.

    Returns ``(inserted, updated)`` counts (determined by comparing the row
    count / changes reported by SQLite before and after).
    """
    col_names = [sql for sql, _src, _typ in columns]
    placeholders = ", ".join("?" for _ in col_names)
    col_list = ", ".join(f'"{c}"' for c in col_names)
    update_clause = ", ".join(
        f'"{c}" = excluded."{c}"' for c in col_names if c != pk
    )

    sql = (
        f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) '
        f'ON CONFLICT("{pk}") DO UPDATE SET {update_clause}'
    )

    # Determine which keys already exist to split inserted vs updated.
    existing_keys = {
        r[0] for r in conn.execute(f'SELECT "{pk}" FROM "{table}"').fetchall()
    }

    inserted = updated = 0
    for rec in rows:
        key = rec.get(pk)
        if key in existing_keys:
            updated += 1
        else:
            inserted += 1
            existing_keys.add(key)
        values = [rec.get(c) for c in col_names]
        conn.execute(sql, values)

    conn.commit()
    return inserted, updated


# ---------------------------------------------------------------------------
# High-level load entry points
# ---------------------------------------------------------------------------

def load_cordis_file(conn: sqlite3.Connection, path: str | Path) -> tuple[int, int]:
    """Read a CORDIS Excel export and upsert it into ``cordis_projects``."""
    df = pd.read_excel(path, engine="openpyxl")
    rows = normalize_cordis(df)
    return upsert_rows(conn, "cordis_projects", CORDIS_COLUMNS, rows, pk="id")


def load_erc_file(conn: sqlite3.Connection, path: str | Path) -> tuple[int, int]:
    """Read an ERC-dashboard Excel dump and upsert it into ``erc_projects``."""
    df = pd.read_excel(path, engine="openpyxl")
    rows = normalize_erc(df)
    return upsert_rows(conn, "erc_projects", ERC_COLUMNS, rows, pk="project_number")
