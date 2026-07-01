"""
CORDIS Data Processor
=====================
Parses raw bytes from the CORDIS API into structured pandas DataFrames
and provides basic analytics / export helpers.
"""

import io
import json
import csv
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# Paths / suffixes that indicate metadata rather than data files inside a ZIP.
_ZIP_SKIP = ("information/", "readme", "changelog", ".pdf", ".txt", ".md")


def _maybe_unzip(raw_bytes: bytes, target_fmt: str) -> bytes:
    """
    Transparently unwrap CORDIS ZIP archives (potentially nested) and return
    the raw data bytes ready for the format-specific parser.

    CORDIS ZIP layout (post 2026-05-06 for JSON):
      EXTRACTION_*.zip
        ├── information.zip   (changelog, field-description PDF)
        └── json.zip
              ├── project-rcn-XXXXXX_en.json   (one file per record)
              └── information/
                    ├── changelog.txt
                    └── DET_fields_description.pdf

    For JSON format the inner archive contains one file per project; we read
    all of them and combine into a single JSON array so the rest of the
    pipeline can normalise the data as usual.
    For all other formats the inner archive typically contains a single file
    which is returned as-is.
    """
    ZIP_MAGIC = b"PK\x03\x04"

    ext_map = {
        "json": ".json",
        "csv": ".csv",
        "xlsx": ".xlsx",
        "xml": ".xml",
        "summary": ".csv",
    }
    wanted_ext = ext_map.get(target_fmt.lower(), "")
    fmt_lower  = target_fmt.lower()

    while raw_bytes.startswith(ZIP_MAGIC):
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            names = zf.namelist()

            # Data files: match wanted extension, skip metadata paths
            data_files = [
                n for n in names
                if n.lower().endswith(wanted_ext)
                and not any(s in n.lower() for s in _ZIP_SKIP)
            ]

            # ── Multiple per-record files (new JSON format: one file/project) ──
            if len(data_files) > 1:
                if wanted_ext == ".json":
                    console.print(
                        f"[dim]ZIP: combining {len(data_files)} individual JSON records[/]"
                    )
                    records = []
                    for name in sorted(data_files):
                        try:
                            records.append(
                                json.loads(zf.read(name).decode("utf-8"))
                            )
                        except Exception as exc:
                            console.print(f"[yellow]⚠ Skipping {name}: {exc}[/]")
                    # Return combined array – no more unzipping needed
                    return json.dumps(records).encode("utf-8")
                else:
                    # CSV / XLSX: take first matching file (single-file per extraction)
                    data_files = [data_files[0]]

            # ── Single exact-extension match ───────────────────────────────────
            if data_files:
                chosen = data_files[0]
                console.print(f"[dim]ZIP layer detected – extracting: {chosen}[/]")
                raw_bytes = zf.read(chosen)
                # XLSX is itself a ZIP – stop here to avoid re-entering the loop
                if wanted_ext and chosen.lower().endswith(wanted_ext):
                    break
                continue

            # ── Look for a format-named inner ZIP (e.g. "json.zip") ───────────
            fmt_zip = next(
                (n for n in names
                 if fmt_lower in n.lower().split(".")[0]
                 and n.lower().endswith(".zip")),
                None,
            )
            if fmt_zip:
                console.print(f"[dim]ZIP layer detected – extracting: {fmt_zip}[/]")
                raw_bytes = zf.read(fmt_zip)
                continue

            # ── Last resort: skip known non-data files, take first remaining ──
            candidates = [n for n in names if not any(s in n.lower() for s in _ZIP_SKIP)]
            chosen = (candidates or names)[0]
            console.print(f"[dim]ZIP layer detected – extracting: {chosen}[/]")
            raw_bytes = zf.read(chosen)

    return raw_bytes


def parse_response(raw_bytes: bytes, output_format: str) -> pd.DataFrame:
    """
    Parse raw bytes from a CORDIS extraction into a pandas DataFrame.

    Parameters
    ----------
    raw_bytes : bytes
        Raw file content returned by the API.  May be a ZIP archive – it will
        be transparently decompressed before parsing.
    output_format : str
        The format that was requested: 'json' | 'csv' | 'xlsx' | 'xml' | 'summary'.

    Returns
    -------
    pd.DataFrame
    """
    raw_bytes = _maybe_unzip(raw_bytes, output_format)
    fmt = output_format.lower()
    if fmt == "json":
        return _parse_json(raw_bytes)
    elif fmt == "csv":
        return _parse_csv(raw_bytes)
    elif fmt == "xlsx":
        return _parse_xlsx(raw_bytes)
    elif fmt == "xml":
        return _parse_xml(raw_bytes)
    elif fmt == "summary":
        return _parse_csv(raw_bytes)   # summary is typically CSV-like
    else:
        raise ValueError(f"Unknown output format: {output_format!r}")


def _parse_json(raw: bytes) -> pd.DataFrame:
    """
    Parse a CORDIS JSON extraction into a flat DataFrame.

    Since 2026-05-06 CORDIS ships one hierarchical JSON file per record.
    We flatten each record with :func:`_flatten_project_record` so that
    nested ``relations.associations`` (organisations, programmes, calls)
    and ``categories`` (EuroSciVoc, funding scheme) are surfaced as
    proper columns rather than raw list-of-dict blobs.
    """
    data = json.loads(raw.decode("utf-8"))

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        for key in ("results", "data", "projects", "records"):
            if key in data:
                records = data[key]
                break
        else:
            records = [data]
    else:
        return pd.DataFrame()

    flat = [_flatten_project_record(r) for r in records]
    return pd.DataFrame(flat)


# ---------------------------------------------------------------------------
# CORDIS JSON flattening helpers
# ---------------------------------------------------------------------------

def _flatten_project_record(record: dict) -> dict:
    """
    Flatten a hierarchical CORDIS project record into a single-level dict.

    Extracts:
    • Top-level scalar fields (id, acronym, title, dates, costs, status, …)
    • identifiers.grantDoi
    • relations.associations → coordinator, all organisations, programme,
      topic, call
    • categories → EuroSciVoc display paths, funding scheme
    """
    SKIP_KEYS = frozenset({"relations", "categories", "identifiers", "validation"})

    flat: dict = {}

    # ── Top-level scalars ────────────────────────────────────────────────────
    for key, val in record.items():
        if key in SKIP_KEYS:
            continue
        if isinstance(val, (str, int, float, bool)) or val is None:
            flat[key] = val

    # ── identifiers ─────────────────────────────────────────────────────────
    identifiers = record.get("identifiers") or {}
    flat["grantDoi"] = identifiers.get("grantDoi", "")

    # ── relations.associations ───────────────────────────────────────────────
    associations = (record.get("relations") or {}).get("associations") or []
    flat.update(_extract_associations(associations))

    # ── categories ──────────────────────────────────────────────────────────
    categories = record.get("categories") or []
    flat.update(_extract_categories(categories))

    return flat


def _extract_associations(associations: list) -> dict:
    """
    Extract key fields from the ``relations.associations`` list.

    Returns a flat dict with:
    • coordinator_name / shortName / country / ecContribution
    • org_names, org_countries  (pipe-separated, all organisations)
    • programme_code / title / frameworkProgramme  (legal basis)
    • topic_code / topic_title
    • call_identifier / call_title
    """
    coordinators: list[dict] = []
    all_orgs:     list[dict] = []
    legal_bases:  list[dict] = []
    topics:       list[dict] = []
    calls:        list[dict] = []

    for assoc in associations:
        ct        = assoc.get("contenttype", "")
        attr      = assoc.get("attributes") or {}
        assoc_type = attr.get("type", "")

        if ct == "organization":
            org = {
                "name":          assoc.get("legalName") or assoc.get("name", ""),
                "shortName":     assoc.get("shortName", ""),
                "country":       (assoc.get("address") or {}).get("country", ""),
                "ecContribution": attr.get("ecContribution", ""),
                "role":          assoc_type,
                "activityType":  "",
                "nutsCode":      "",
                "nutsName":      "",
            }

            # ── nested relations.categories → org activity type ────────────
            org_rel = assoc.get("relations") or {}
            for cat in org_rel.get("categories") or []:
                cat_attr = cat.get("attributes") or {}
                if cat_attr.get("type") == "relatedOrganizationActivityType":
                    org["activityType"] = cat.get("title", "")
                    break

            # ── nested relations.regions → NUTS code ───────────────────────
            for region in org_rel.get("regions") or []:
                reg_attr = region.get("attributes") or {}
                if reg_attr.get("type") == "relatedNutsCode":
                    org["nutsCode"] = region.get("nutsCode", "")
                    org["nutsName"] = region.get("name", "")
                    break

            all_orgs.append(org)
            if assoc_type == "coordinator":
                coordinators.append(org)

        elif ct == "programme":
            if assoc_type == "relatedLegalBasis":
                legal_bases.append({
                    "code":               assoc.get("code", ""),
                    "title":              assoc.get("title", ""),
                    "frameworkProgramme": assoc.get("frameworkProgramme", ""),
                })
            elif assoc_type == "relatedTopic":
                topics.append({
                    "code":  assoc.get("code", ""),
                    "title": assoc.get("title", ""),
                })

        elif ct == "call" and assoc_type in ("relatedMasterCall", "relatedSubCall"):
            if assoc_type == "relatedMasterCall":
                calls.append({
                    "identifier": assoc.get("identifier") or assoc.get("id", ""),
                    "title":      assoc.get("title", ""),
                })

    result: dict = {}

    # Coordinator
    if coordinators:
        c = coordinators[0]
        result["coordinator_name"]           = c["name"]
        result["coordinator_shortName"]      = c["shortName"]
        result["coordinator_country"]        = c["country"]
        result["coordinator_ecContribution"] = c["ecContribution"]
        result["coordinator_activityType"]   = c.get("activityType", "")
        result["coordinator_nutsCode"]       = c.get("nutsCode", "")
        result["coordinator_nutsName"]       = c.get("nutsName", "")

    # All organisations (pipe-separated)
    result["org_names"]     = " | ".join(o["name"]    for o in all_orgs if o["name"])
    result["org_countries"] = " | ".join(o["country"] for o in all_orgs if o["country"])

    # Legal basis / framework programme
    if legal_bases:
        lb = legal_bases[0]
        result["programme_code"]        = lb["code"]
        result["programme_title"]       = lb["title"]
        result["frameworkProgramme"]    = lb["frameworkProgramme"]

    # Topic
    if topics:
        result["topic_code"]  = topics[0]["code"]
        result["topic_title"] = topics[0]["title"]

    # Call
    if calls:
        result["call_identifier"] = calls[0]["identifier"]
        result["call_title"]      = calls[0]["title"]

    return result


def _extract_categories(categories: list) -> dict:
    """
    Extract EuroSciVoc field-of-science paths and funding scheme from the
    top-level ``categories`` list.

    Returns a flat dict with:
    • euroSciVoc  – pipe-separated display paths
    • fundingScheme – pipe-separated scheme titles
    """
    euro_sci_voc:   list[str] = []
    funding_schemes: list[str] = []

    for cat in categories:
        attr       = cat.get("attributes") or {}
        cat_type   = attr.get("type", "")
        classif    = attr.get("classification", "")

        if cat_type == "isInFieldOfScience" and classif == "euroSciVoc":
            label = cat.get("displayCode") or cat.get("title", "")
            if label:
                euro_sci_voc.append(label)

        elif cat_type == "relatedProjectFundingSchemeCategory":
            label = cat.get("title") or cat.get("code", "")
            if label:
                funding_schemes.append(label)

    result: dict = {}
    if euro_sci_voc:
        result["euroSciVoc"] = " | ".join(euro_sci_voc)
    if funding_schemes:
        result["fundingScheme"] = " | ".join(funding_schemes)
    return result


def _parse_csv(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8-sig")  # handle BOM
    return pd.read_csv(io.StringIO(text))


# Candidate column names used as the join key across CORDIS XLSX sheets.
_JOIN_KEY_CANDIDATES = ("projectID", "id", "projectId", "project_id", "rcn")


def _parse_xlsx(raw: bytes) -> pd.DataFrame:
    """
    Read and merge all sheets from a CORDIS XLSX export into a single DataFrame.

    CORDIS workbooks contain a main project sheet plus several auxiliary sheets
    (flags, topics, programmes, etc.) all sharing a common ``projectID`` key.
    We identify the join key automatically and left-join every auxiliary sheet
    onto the main project sheet so the returned DataFrame contains the full
    dataset.

    If no common key is found the sheet with the most columns is returned as-is.
    """
    buf = io.BytesIO(raw)
    all_sheets: dict[str, pd.DataFrame] = pd.read_excel(
        buf, sheet_name=None, engine="openpyxl"
    )

    if not all_sheets:
        return pd.DataFrame()

    if len(all_sheets) == 1:
        return next(iter(all_sheets.values()))

    console.print(f"[dim]XLSX: {len(all_sheets)} sheets – {', '.join(all_sheets.keys())}[/]")

    # ── Find the join key ────────────────────────────────────────────────────
    join_key: str | None = None
    for candidate in _JOIN_KEY_CANDIDATES:
        if all(candidate in df.columns for df in all_sheets.values()):
            join_key = candidate
            break
    # Fall back: first key that appears in at least the largest sheet
    if join_key is None:
        largest = max(all_sheets.values(), key=lambda d: len(d.columns))
        for candidate in _JOIN_KEY_CANDIDATES:
            if candidate in largest.columns:
                join_key = candidate
                break

    # ── Identify the "main" sheet ────────────────────────────────────────────
    preferred_names = ("project", "projects", "data", "results", "extraction", "export")
    main_df: pd.DataFrame | None = None
    main_name: str = ""
    for name, df in all_sheets.items():
        if name.lower() in preferred_names:
            main_df, main_name = df, name
            break
    if main_df is None:
        # Use the sheet with the most columns as the main sheet
        main_name, main_df = max(all_sheets.items(), key=lambda kv: len(kv[1].columns))

    console.print(f"[dim]XLSX: main sheet → '{main_name}' ({len(main_df.columns)} cols)[/]")

    if join_key is None or join_key not in main_df.columns:
        # Cannot merge – return main sheet only
        console.print("[dim]XLSX: no common join key found; returning main sheet only[/]")
        return main_df

    # ── Merge all other sheets onto the main sheet ───────────────────────────
    merged = main_df.copy()
    for name, df in all_sheets.items():
        if name == main_name:
            continue
        if join_key not in df.columns:
            console.print(f"[dim]XLSX: skipping sheet '{name}' (no '{join_key}' column)[/]")
            continue
        # Drop columns already present in merged (except the join key)
        new_cols = [join_key] + [c for c in df.columns if c not in merged.columns]
        merged = merged.merge(df[new_cols], on=join_key, how="left")
        console.print(
            f"[dim]XLSX: merged sheet '{name}' (+{len(new_cols) - 1} cols)[/]"
        )

    console.print(
        f"[dim]XLSX: final shape {merged.shape[0]} rows × {merged.shape[1]} cols[/]"
    )
    return merged


def _parse_xml(raw: bytes) -> pd.DataFrame:
    """Flatten XML into a DataFrame (best-effort)."""
    root = ET.fromstring(raw)
    records = []
    # Look for child elements that represent individual records
    for child in root:
        record = {}
        _flatten_xml_element(child, "", record)
        records.append(record)
    return pd.DataFrame(records)


def _flatten_xml_element(element: ET.Element, prefix: str, out: dict):
    tag = f"{prefix}{element.tag}" if not prefix else f"{prefix}.{element.tag}"
    if element.text and element.text.strip():
        out[tag] = element.text.strip()
    for attr_name, attr_val in element.attrib.items():
        out[f"{tag}@{attr_name}"] = attr_val
    for child in element:
        _flatten_xml_element(child, tag, out)


# ---------------------------------------------------------------------------
# Summary / analytics
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame, title: str = "CORDIS Extraction Results"):
    """Print a rich summary table of the DataFrame to the console."""
    console.rule(f"[bold blue]{title}[/]")
    console.print(f"[green]Total records:[/] {len(df)}")
    console.print(f"[green]Columns ({len(df.columns)}):[/] {', '.join(df.columns.tolist())}")
    console.print()

    if df.empty:
        console.print("[yellow]No records found.[/]")
        return

    # Show the first few rows in a table
    preview_cols = df.columns[:8].tolist()  # max 8 cols for readability
    table = Table(title="Preview (first 10 rows)", show_lines=True)
    for col in preview_cols:
        table.add_column(col, overflow="fold", max_width=30)
    for _, row in df.head(10).iterrows():
        table.add_row(*[str(row[c]) if pd.notna(row.get(c)) else "" for c in preview_cols])
    console.print(table)


def basic_analytics(df: pd.DataFrame) -> dict:
    """
    Compute basic analytics on extracted project data.

    Returns a dict with summary statistics (works best with project data).
    """
    stats = {}
    stats["total_projects"] = len(df)

    # Funding / EC contribution
    for col_candidate in ["ecMaxContribution", "totalCost", "grantDoi", "id"]:
        if col_candidate in df.columns:
            stats["id_column"] = col_candidate
            break

    # Count by status if available
    for col in ["status", "projectStatus", "fundingScheme"]:
        if col in df.columns:
            stats[f"by_{col}"] = df[col].value_counts().to_dict()

    # Funding totals
    for col in ["ecMaxContribution", "totalCost"]:
        if col in df.columns:
            numeric = pd.to_numeric(df[col], errors="coerce")
            stats[f"total_{col}"] = numeric.sum()
            stats[f"mean_{col}"] = numeric.mean()

    return stats


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def save_dataframe(
    df: pd.DataFrame,
    path: str | Path,
    fmt: str = "csv",
) -> Path:
    """
    Save a DataFrame to disk.

    Parameters
    ----------
    df : pd.DataFrame
    path : str or Path
        Output file path (extension can be omitted; it will be appended).
    fmt : str
        'csv' | 'xlsx' | 'json' | 'parquet'.

    Returns
    -------
    Path  – the actual path written.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Ensure correct extension
    if out.suffix.lower() not in {".csv", ".xlsx", ".json", ".parquet"}:
        out = out.with_suffix(f".{fmt}")

    if fmt == "csv":
        df.to_csv(out, index=False)
    elif fmt == "xlsx":
        df.to_excel(out, index=False, engine="openpyxl")
    elif fmt == "json":
        df.to_json(out, orient="records", indent=2, force_ascii=False)
    elif fmt == "parquet":
        df.to_parquet(out, index=False)
    else:
        raise ValueError(f"Unsupported save format: {fmt!r}")

    console.print(f"[bold green]✓ Saved {len(df)} records → {out}[/]")
    return out


def save_raw(raw_bytes: bytes, path: str | Path) -> Path:
    """Save raw bytes from the API to disk (preserves original format)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw_bytes)
    console.print(f"[bold green]✓ Saved raw response ({len(raw_bytes):,} bytes) → {out}[/]")
    return out
