"""
Database schema for the Heidelberg EU-projects SQLite database.
================================================================

This module is the single source of truth for:

* Where the database lives (:data:`DB_PATH`).
* How to open a connection (:func:`get_connection`).
* The column layout of the two base tables and how they map to the raw
  Excel column names (:data:`CORDIS_COLUMNS`, :data:`ERC_COLUMNS`).
* The DDL that (re)creates the tables, the change-log and the staging table
  (:func:`create_schema`).

Design overview
---------------
Two base tables mirror the two authoritative sources:

``cordis_projects``
    One row per EU project of Universität Heidelberg (UHEI) and
    Universitätsklinikum Heidelberg (UKHD). Primary key ``id`` (the CORDIS
    project id). This is the *authoritative base* – every project lives here.

``erc_projects``
    One row per ERC grant from the ERC-dashboard dump. Primary key
    ``project_number`` (the ERC "Project Number"). This is *supplementary*:
    it only adds ERC-specific fields (PI, panel, domain, call year, …).

The consolidated ``heidelberg_projects`` view (see ``build_views.py``) left-
joins ``erc_projects`` onto ``cordis_projects`` on
``cordis_projects.id = erc_projects.project_number`` so that **every** CORDIS
project is present, with ERC columns filled only where a match exists.

Two housekeeping tables support the delta-update workflow (Task 2):

``update_log``
    Append-only audit trail: timestamp, source file, inserted/updated counts.

``cordis_staging``
    Transient landing zone for a freshly downloaded CORDIS export before it is
    upserted into ``cordis_projects``. Mirrors the ``cordis_projects`` columns.

Assumptions (please review)
---------------------------
* The join key is reliable: CORDIS ``id`` == ERC ``Project Number``. In the
  sample data 96 of 373 CORDIS projects matched an ERC row – consistent with
  "some projects are ERC, most are not".
* Dates arrive as ISO strings (CORDIS: ``YYYY-MM-DD``; ERC: ``YYYY-MM-DD
  00:00:00``). They are stored as TEXT in ISO ``YYYY-MM-DD`` form so that
  string comparison == chronological comparison, and derived ``start_year`` /
  ``end_year`` INTEGER columns are added for fast range filtering.
* Monetary fields (``total_cost``, ``ec_max_contribution``,
  ``eu_contribution``) are stored as REAL.
* All other fields are stored as TEXT/INTEGER as detected from the exports.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Location of the database file
# ---------------------------------------------------------------------------
# Resolve relative to the project root (two levels up from this file:
#   src/db/schema.py -> src -> <project root>)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "cordis_heidelberg.db"


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------
# Each entry is a triple:  (sql_column, source_excel_column, sql_type)
#
# * sql_column          – snake_case name used inside SQLite.
# * source_excel_column – exact header as it appears in the Excel export
#                         (None => derived column, not read directly).
# * sql_type            – SQLite storage class.
#
# The CORDIS export already uses tidy camelCase headers, so we keep the SQL
# names identical where sensible (only lower-casing a couple for consistency).
# ---------------------------------------------------------------------------

# (sql_name, excel_header_or_None, sql_type)
CORDIS_COLUMNS: list[tuple[str, str | None, str]] = [
    ("id",                          "id",                          "INTEGER"),  # PK / join key
    ("rcn",                         "rcn",                         "INTEGER"),
    ("contenttype",                 "contenttype",                 "TEXT"),
    ("language",                    "language",                    "TEXT"),
    ("available_languages",         "availableLanguages",          "TEXT"),
    ("acronym",                     "acronym",                     "TEXT"),
    ("title",                       "title",                       "TEXT"),
    ("teaser",                      "teaser",                      "TEXT"),
    ("objective",                   "objective",                   "TEXT"),
    ("description",                 "description",                 "TEXT"),
    ("total_cost",                  "totalCost",                   "REAL"),
    ("ec_max_contribution",         "ecMaxContribution",           "REAL"),
    ("start_date",                  "startDate",                   "TEXT"),
    ("end_date",                    "endDate",                     "TEXT"),
    ("start_year",                  None,                          "INTEGER"),  # derived
    ("end_year",                    None,                          "INTEGER"),  # derived
    ("duration",                    "duration",                    "INTEGER"),
    ("status",                      "status",                      "TEXT"),
    ("grant_doi",                   "grantDoi",                    "TEXT"),
    ("coordinator_name",            "coordinator_name",            "TEXT"),
    ("coordinator_short_name",      "coordinator_shortName",       "TEXT"),
    ("coordinator_country",         "coordinator_country",         "TEXT"),
    ("coordinator_ec_contribution", "coordinator_ecContribution",  "REAL"),
    ("coordinator_activity_type",   "coordinator_activityType",    "TEXT"),
    ("coordinator_nuts_code",       "coordinator_nutsCode",        "TEXT"),
    ("coordinator_nuts_name",       "coordinator_nutsName",        "TEXT"),
    ("org_names",                   "org_names",                   "TEXT"),
    ("org_countries",               "org_countries",               "TEXT"),
    ("programme_code",              "programme_code",              "TEXT"),
    ("programme_title",             "programme_title",             "TEXT"),
    ("programme_label",             None,                          "TEXT"),     # derived
    ("framework_programme",         "frameworkProgramme",          "TEXT"),
    ("topic_code",                  "topic_code",                  "TEXT"),
    ("topic_title",                 "topic_title",                 "TEXT"),
    ("call_identifier",             "call_identifier",             "TEXT"),
    ("call_title",                  "call_title",                  "TEXT"),
    ("call_year",                   None,                          "INTEGER"),  # derived
    ("keywords",                    "keywords",                    "TEXT"),
    ("ec_signature_date",           "ecSignatureDate",             "TEXT"),
    ("content_creation_date",       "contentCreationDate",         "TEXT"),
    ("content_update_date",         "contentUpdateDate",           "TEXT"),
    ("last_update_date",            "lastUpdateDate",              "TEXT"),
    ("source_update_date",          "sourceUpdateDate",            "TEXT"),
    ("archived_date",               "archivedDate",                "TEXT"),
    ("termination_date",            "terminationDate",             "TEXT"),
    ("model_version",               "modelVersion",                "TEXT"),
    ("ica_version",                 "icaVersion",                  "TEXT"),
]

# Convenience: the derived flag on whether a UHEI/UKHD org is the coordinator
# is computed in the view, so no dedicated stored column is needed here.

# (sql_name, excel_header_or_None, sql_type)
ERC_COLUMNS: list[tuple[str, str | None, str]] = [
    ("project_number",  "Project Number",       "INTEGER"),  # PK / join key
    ("programme",       "Programme",            "TEXT"),
    ("acronym",         "Acronym",              "TEXT"),
    ("project_title",   "Project Title",        "TEXT"),
    ("abstract",        "Abstract",             "TEXT"),
    ("researcher",      "Researcher(s)",        "TEXT"),   # PI name(s)
    ("host_institution","Host Institution(s)",  "TEXT"),
    ("country",         "Country",              "TEXT"),
    ("region",          "Region",               "TEXT"),
    ("call",            "Call",                 "TEXT"),
    ("grant_type",      "Grant Type",           "TEXT"),   # Starting/Consolidator/…
    ("domain",          "Domain",               "TEXT"),   # LS / PE / SH
    ("panel",           "Panel",                "TEXT"),   # e.g. LS1 - Molecules of Life
    ("call_year",       "Call Year",            "INTEGER"),
    ("start_date",      "Start Date",           "TEXT"),
    ("end_date",        "End Date",             "TEXT"),
    ("eu_contribution", "EU contribution",      "REAL"),
    ("cordis_link",     "CORDIS Link",          "TEXT"),
]

# Reverse lookup used by the loader: {excel_header: sql_column}
CORDIS_SOURCE_TO_SQL: dict[str, str] = {
    src: sql for sql, src, _ in CORDIS_COLUMNS if src is not None
}
ERC_SOURCE_TO_SQL: dict[str, str] = {
    src: sql for sql, src, _ in ERC_COLUMNS if src is not None
}


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """
    Open a SQLite connection with sensible defaults.

    * ``row_factory`` = :class:`sqlite3.Row` so rows behave like dicts.
    * Foreign keys enabled (harmless even though we keep the schema flat).
    * ``PRAGMA journal_mode = WAL`` for better concurrent read performance
      (the web app reads while the ETL may write).
    """
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

def _column_ddl(columns: list[tuple[str, str | None, str]], pk: str) -> str:
    """Build the ``col TYPE`` fragment list, marking *pk* as PRIMARY KEY."""
    parts = []
    for sql_name, _src, sql_type in columns:
        if sql_name == pk:
            parts.append(f'"{sql_name}" {sql_type} PRIMARY KEY')
        else:
            parts.append(f'"{sql_name}" {sql_type}')
    return ",\n    ".join(parts)


def create_schema(conn: sqlite3.Connection) -> None:
    """
    Create every base/housekeeping table if it does not already exist.

    Tables created:
      * cordis_projects   (base, PK id)
      * erc_projects      (supplementary, PK project_number)
      * cordis_staging    (transient, same columns as cordis_projects)
      * update_log        (audit trail)

    Indexes and the consolidated view are handled in ``build_views.py`` so
    that they can be refreshed independently after a data load.
    """
    cordis_cols = _column_ddl(CORDIS_COLUMNS, pk="id")
    erc_cols = _column_ddl(ERC_COLUMNS, pk="project_number")
    # Staging mirrors cordis_projects but WITHOUT a primary-key constraint,
    # so a re-download containing (accidental) duplicate ids still lands.
    staging_cols = ",\n    ".join(
        f'"{sql_name}" {sql_type}' for sql_name, _src, sql_type in CORDIS_COLUMNS
    )

    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS cordis_projects (
            {cordis_cols}
        );

        CREATE TABLE IF NOT EXISTS erc_projects (
            {erc_cols}
        );

        CREATE TABLE IF NOT EXISTS cordis_staging (
            {staging_cols}
        );

        CREATE TABLE IF NOT EXISTS update_log (
            log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT NOT NULL,
            source_file   TEXT,
            table_name    TEXT,
            rows_read     INTEGER DEFAULT 0,
            rows_inserted INTEGER DEFAULT 0,
            rows_updated  INTEGER DEFAULT 0,
            note          TEXT
        );
        """
    )
    conn.commit()


def drop_all(conn: sqlite3.Connection) -> None:
    """
    Drop the view and all tables. Used by ``--recreate`` to rebuild from
    scratch. The ``update_log`` is intentionally preserved history-wise only
    when the caller wants it; here we drop everything for a clean slate.
    """
    conn.executescript(
        """
        DROP VIEW  IF EXISTS heidelberg_projects;
        DROP TABLE IF EXISTS cordis_staging;
        DROP TABLE IF EXISTS erc_projects;
        DROP TABLE IF EXISTS cordis_projects;
        DROP TABLE IF EXISTS update_log;
        """
    )
    conn.commit()
