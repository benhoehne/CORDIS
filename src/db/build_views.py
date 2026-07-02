"""
Consolidated view + indexes for the Heidelberg EU-projects database.
====================================================================

The ``heidelberg_projects`` view is the object the web/export layer reads
from. It uses ``cordis_projects`` as the base and LEFT JOINs
``erc_projects`` on ``cordis_projects.id = erc_projects.project_number`` so
that:

* Every CORDIS project is present exactly once.
* ERC-only columns (PI, panel, domain, call year, …) are filled where a match
  exists and NULL otherwise.

We expose ERC columns under explicit ``erc_*`` names to avoid clashing with
the CORDIS columns of the same concept (e.g. ``acronym`` vs ``erc_acronym``),
and we add two convenience flags:

* ``is_erc``          – 1 when an ERC row matched, else 0.
* ``institution``     – 'UKHD' / 'UHEI' / 'UHEI+UKHD' derived from org_names,
                         so the UI can filter by institution without parsing
                         the pipe-separated org string every time.

Indexes are created on the *base tables* (SQLite cannot index a view) on the
columns the UI filters/sorts by; the view inherits their benefit through the
query planner.
"""

from __future__ import annotations

import sqlite3

# Substrings that identify each Heidelberg institution inside org_names /
# coordinator_name. Kept here so the classification rule is reviewable.
UHEI_MARKERS = ("RUPRECHT-KARLS-UNIVERSITAET HEIDELBERG", "UHEI")
UKHD_MARKERS = ("UNIVERSITATSKLINIKUM HEIDELBERG", "UKHD")


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

def build_view(conn: sqlite3.Connection) -> None:
    """
    (Re)create the ``heidelberg_projects`` consolidated view.

    Safe to call repeatedly – it drops and recreates the view so schema
    changes propagate. The view is read-only; all writes go to the base
    tables via the loaders / ETL.
    """
    # Institution classification is done with CASE + LIKE on org_names so that
    # a project involving both institutions is labelled 'UHEI+UKHD'.
    uhei_like = " OR ".join(
        f"c.org_names LIKE '%{m}%'" for m in UHEI_MARKERS
    )
    ukhd_like = " OR ".join(
        f"c.org_names LIKE '%{m}%'" for m in UKHD_MARKERS
    )

    conn.executescript(
        f"""
        DROP VIEW IF EXISTS heidelberg_projects;

        CREATE VIEW heidelberg_projects AS
        SELECT
            -- ── CORDIS base fields ─────────────────────────────────────────
            c.id                              AS id,
            c.rcn                             AS rcn,
            c.acronym                         AS acronym,
            c.title                           AS title,
            c.teaser                          AS teaser,
            c.objective                       AS objective,
            c.status                          AS status,
            c.total_cost                      AS total_cost,
            c.ec_max_contribution             AS ec_max_contribution,
            c.start_date                      AS start_date,
            c.end_date                        AS end_date,
            c.start_year                      AS start_year,
            c.end_year                        AS end_year,
            c.duration                        AS duration,
            c.grant_doi                       AS grant_doi,
            c.coordinator_name                AS coordinator_name,
            c.coordinator_short_name          AS coordinator_short_name,
            c.coordinator_country             AS coordinator_country,
            c.org_names                       AS org_names,
            c.org_countries                   AS org_countries,
            c.programme_code                  AS programme_code,
            c.programme_title                 AS programme_title,
            c.programme_label                 AS programme_label,
            c.framework_programme             AS framework_programme,
            c.topic_code                      AS topic_code,
            c.topic_title                     AS topic_title,
            c.call_identifier                 AS call_identifier,
            c.call_title                      AS call_title,
            -- Unified call year: prefer the CORDIS-derived year, fall back to
            -- the ERC dashboard's own "Call Year" where CORDIS has none.
            COALESCE(c.call_year, e.call_year) AS call_year,
            c.keywords                        AS keywords,

            -- ── Derived helpers ────────────────────────────────────────────
            CASE
                WHEN ({uhei_like}) AND ({ukhd_like}) THEN 'UHEI+UKHD'
                WHEN ({ukhd_like})                    THEN 'UKHD'
                WHEN ({uhei_like})                    THEN 'UHEI'
                ELSE NULL
            END                               AS institution,
            CASE WHEN e.project_number IS NOT NULL THEN 1 ELSE 0 END
                                              AS is_erc,

            -- ── ERC supplementary fields (NULL for non-ERC projects) ───────
            e.project_number                  AS erc_project_number,
            e.researcher                      AS erc_pi,
            e.panel                           AS erc_panel,
            e.domain                          AS erc_domain,
            e.grant_type                      AS erc_grant_type,
            e.call                            AS erc_call,
            e.call_year                       AS erc_call_year,
            e.programme                       AS erc_programme,
            e.host_institution                AS erc_host_institution,
            e.country                         AS erc_country,
            e.region                          AS erc_region,
            e.eu_contribution                 AS erc_eu_contribution,
            e.cordis_link                     AS erc_cordis_link,
            -- Build a CORDIS URL for convenience in the UI
            'https://cordis.europa.eu/project/id/' || c.id AS cordis_url
        FROM cordis_projects c
        LEFT JOIN erc_projects e
               ON c.id = e.project_number;
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

def build_indexes(conn: sqlite3.Connection) -> None:
    """
    Create indexes on the base tables to keep the UI filters snappy.

    SQLite cannot index a view directly, so we index the underlying columns.
    ``CREATE INDEX IF NOT EXISTS`` makes this idempotent.
    """
    conn.executescript(
        """
        -- cordis_projects -------------------------------------------------
        CREATE INDEX IF NOT EXISTS idx_cordis_acronym
            ON cordis_projects (acronym);
        CREATE INDEX IF NOT EXISTS idx_cordis_title
            ON cordis_projects (title);
        CREATE INDEX IF NOT EXISTS idx_cordis_call
            ON cordis_projects (call_identifier);
        CREATE INDEX IF NOT EXISTS idx_cordis_programme
            ON cordis_projects (programme_code);
        CREATE INDEX IF NOT EXISTS idx_cordis_programme_label
            ON cordis_projects (programme_label);
        CREATE INDEX IF NOT EXISTS idx_cordis_call_year
            ON cordis_projects (call_year);
        CREATE INDEX IF NOT EXISTS idx_cordis_framework
            ON cordis_projects (framework_programme);
        CREATE INDEX IF NOT EXISTS idx_cordis_coord_country
            ON cordis_projects (coordinator_country);
        CREATE INDEX IF NOT EXISTS idx_cordis_start_year
            ON cordis_projects (start_year);
        CREATE INDEX IF NOT EXISTS idx_cordis_end_year
            ON cordis_projects (end_year);
        CREATE INDEX IF NOT EXISTS idx_cordis_status
            ON cordis_projects (status);

        -- erc_projects ----------------------------------------------------
        CREATE INDEX IF NOT EXISTS idx_erc_panel
            ON erc_projects (panel);
        CREATE INDEX IF NOT EXISTS idx_erc_domain
            ON erc_projects (domain);
        CREATE INDEX IF NOT EXISTS idx_erc_grant_type
            ON erc_projects (grant_type);
        CREATE INDEX IF NOT EXISTS idx_erc_call_year
            ON erc_projects (call_year);
        CREATE INDEX IF NOT EXISTS idx_erc_researcher
            ON erc_projects (researcher);
        """
    )
    conn.commit()


def refresh(conn: sqlite3.Connection) -> None:
    """Convenience: rebuild indexes + view together (call after any load)."""
    build_indexes(conn)
    build_view(conn)
