"""
Database package for the CORDIS / Heidelberg EU-projects workflow.

Modules
-------
schema       : SQLite connection helpers, column mappings, DDL (CREATE TABLE).
load_excel   : Read the CORDIS / ERC Excel exports and populate the tables.
build_views  : Create the consolidated ``heidelberg_projects`` view + indexes.
"""

from .schema import (
    DB_PATH,
    get_connection,
    create_schema,
    drop_all,
    CORDIS_COLUMNS,
    ERC_COLUMNS,
    ERC_SOURCE_TO_SQL,
)

__all__ = [
    "DB_PATH",
    "get_connection",
    "create_schema",
    "drop_all",
    "CORDIS_COLUMNS",
    "ERC_COLUMNS",
    "ERC_SOURCE_TO_SQL",
]
