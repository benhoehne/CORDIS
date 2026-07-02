"""
FastAPI application – JSON API + static frontend + Excel export (Task 3).
========================================================================

Layers
------
* Data access .......... ``src/web/repository.py``  (SQLite queries)
* API endpoints (JSON) . this module, ``/api/*``
* Frontend ............. ``src/web/static/index.html`` (served at ``/``)
* Excel export ......... ``src/web/export.py`` (``/api/export`` route)

Endpoints
---------
GET  /                     -> the single-page frontend
GET  /api/projects         -> paginated, filtered list (JSON)
GET  /api/projects/{id}    -> full detail of one project (JSON)
GET  /api/facets           -> distinct values for dropdown filters
GET  /api/export           -> build an .xlsx of the filtered subset,
                              returns the file for download

Run
---
    uvicorn src.web.app:app --reload
or
    python run.py web
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .repository import (
    ProjectFilters,
    query_projects,
    get_project,
    distinct_values,
)
from .export import export_filtered, build_export_filename

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Heidelberg EU Projects",
    description="Explore and export consolidated CORDIS + ERC data for "
                "Universität Heidelberg (UHEI) and Universitätsklinikum "
                "Heidelberg (UKHD).",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# API – list / detail
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def api_projects(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort: str = "start_year",
    direction: str = "desc",
):
    """Return a filtered, paginated page of projects as JSON."""
    # Pass the raw QueryParams object so multi-value programme_label is preserved.
    filters = ProjectFilters.from_query_params(request.query_params)
    return query_projects(
        filters, page=page, page_size=page_size, sort=sort, direction=direction
    )


@app.get("/api/projects/{project_id}")
def api_project_detail(project_id: int):
    """Return the full record of a single project."""
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/api/facets")
def api_facets():
    """
    Return distinct values used to populate the UI dropdowns.

    Kept in one call so the frontend can build all selectors on load.
    """
    return {
        "institution": distinct_values("institution"),
        "status": distinct_values("status"),
        "programme_label": distinct_values("programme_label"),
        "framework_programme": distinct_values("framework_programme"),
        "programme_code": distinct_values("programme_code"),
        "erc_panel": distinct_values("erc_panel"),
        "erc_domain": distinct_values("erc_domain"),
        "erc_grant_type": distinct_values("erc_grant_type"),
    }


# ---------------------------------------------------------------------------
# API – export
# ---------------------------------------------------------------------------

@app.get("/api/export")
def api_export(request: Request):
    """
    Build an Excel export of the currently filtered subset and return it as a
    download. The same query-string filters as ``/api/projects`` apply.
    """
    filters = ProjectFilters.from_query_params(request.query_params)
    path = export_filtered(filters)
    return FileResponse(
        path,
        filename=path.name,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


# ---------------------------------------------------------------------------
# Frontend (mounted last so /api/* takes precedence)
# ---------------------------------------------------------------------------

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:  # pragma: no cover - defensive
    @app.get("/")
    def _missing_static():
        return JSONResponse(
            {"error": f"Static directory not found: {STATIC_DIR}"},
            status_code=500,
        )
