# CORDIS Data Query Tool

A Python tool for querying the [CORDIS Data Extraction REST API](https://cordis.europa.eu/dataextractions/api-docs-ui), designed for data analysis, visualisation, and future dashboard integration.

---

## 🆕 Heidelberg EU-Projects Database, Delta Updates & Web App

Beyond the API extraction described below, this repo now includes a full
**SQLite consolidation + delta-update + web/export workflow** for the EU
projects of Universität Heidelberg (UHEI) and Universitätsklinikum Heidelberg
(UKHD), combining the CORDIS export with the ERC dashboard dump.

```bash
pip install -r requirements.txt

python manage.py db build --recreate        # build data/cordis_heidelberg.db
python manage.py db update  <new_cordis.xlsx>   # idempotent delta update
python manage.py db update-erc <new_erc.xlsx>   # refresh ERC enrichment
python manage.py db export --erc-only --year-from 2024 --institution UKHD
python manage.py web --port 8000            # → http://127.0.0.1:8000
```

See **[`docs/DATABASE_WORKFLOW.md`](docs/DATABASE_WORKFLOW.md)** for the schema,
column mappings, ETL pipeline and web-layer architecture.

---

## Features

- **Async extraction flow** — submits jobs, polls for completion, downloads results automatically
- **Multiple output formats** — JSON, CSV, XLSX, XML, or summary
- **Pre-built Heidelberg ERC query** — ERC-funded projects (Horizon Europe + H2020) for UHD & UKHD
- **Generic query builder** — compose queries programmatically
- **Rich terminal output** — progress bars, tables, analytics summary
- **Export to CSV / XLSX / JSON / Parquet** — ready for pandas, dashboards, BI tools
- **CLI tool** — for ad-hoc queries and automation

---

## Project Structure

```
CORDIS/
├── src/
│   ├── __init__.py
│   ├── cordis_client.py      ← CORDIS REST API client (async extraction)
│   ├── query_builder.py      ← Query string builder + pre-built queries
│   └── data_processor.py     ← Parsing, analytics, export helpers
├── data/                     ← Output files (created at runtime)
├── query_heidelberg_erc.py   ← Dedicated script: Heidelberg ERC projects
├── cordis_cli.py             ← Generic CLI for any CORDIS query
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Get a CORDIS API key

1. Go to [https://cordis.europa.eu/dataextractions/api-docs-ui](https://cordis.europa.eu/dataextractions/api-docs-ui)
2. Register / log in and generate an API key
3. Copy `.env.example` to `.env` and add your key:

```bash
cp .env.example .env
# edit .env and set CORDIS_API_KEY=your_key_here
```

---

## Usage

### Heidelberg ERC Query

The target query retrieves all ERC projects (Horizon Europe **HORIZON.1.1** + H2020 **H2020-EU.1.1.**) associated with:
- `RUPRECHT-KARLS-UNIVERSITAET HEIDELBERG`
- `UNIVERSITATSKLINIKUM HEIDELBERG`

#### Dedicated script

```bash
# Basic run (JSON from API, saved as CSV)
python query_heidelberg_erc.py

# Choose API output format and local save format
python query_heidelberg_erc.py --format csv --save-format xlsx

# Save raw API response too
python query_heidelberg_erc.py --save-raw

# Include archived projects
python query_heidelberg_erc.py --archived

# Dry-run: print query string only
python query_heidelberg_erc.py --show-query

# Suppress file output
python query_heidelberg_erc.py --no-save
```

#### Via the generic CLI

```bash
python cordis_cli.py heidelberg-erc --key YOUR_KEY
python cordis_cli.py heidelberg-erc --key YOUR_KEY --format xlsx --save-format xlsx
```

---

### Generic CLI

```bash
# Run any CORDIS query
python cordis_cli.py query \
    --key YOUR_KEY \
    --query "contenttype='project' AND title='cancer'" \
    --format json \
    --save-format csv

# List recent extraction tasks for your key
python cordis_cli.py list-tasks --key YOUR_KEY

# Show a pre-built query string (dry-run)
python cordis_cli.py show-query heidelberg-erc

# Cancel a running task
python cordis_cli.py cancel --key YOUR_KEY 12345

# Delete a completed task
python cordis_cli.py delete --key YOUR_KEY 12345

# Help
python cordis_cli.py --help
python cordis_cli.py query --help
```

---

## CORDIS Query Syntax

The query language uses OData-like syntax:

```
contenttype='project' AND title='quantum'
contenttype='project' AND startYear>=2020
relations/associations/programme/code='HORIZON.1.1'
relations/associations/organization/legalName='MY UNIVERSITY'
```

Combine with `AND`, `OR`, and group with `()`.

---

## The Exact Heidelberg ERC Query

```
contenttype='project' AND (relations/associations/programme/code='HORIZON.1.1' OR relations/associations/programme/code='H2020-EU.1.1.') AND (relations/associations/organization/legalName='RUPRECHT-KARLS-UNIVERSITAET HEIDELBERG' OR relations/associations/organization/shortName='RUPRECHT-KARLS-UNIVERSITAET HEIDELBERG' OR relations/associations/organization/legalName='UNIVERSITATSKLINIKUM HEIDELBERG' OR relations/associations/organization/shortName='UNIVERSITATSKLINIKUM HEIDELBERG')
```

---

## API Flow (How It Works)

The CORDIS extraction API is **asynchronous**:

```
1. GET /api/dataextractions/getExtraction?query=...&key=...&outputFormat=json
   → { taskID: 12345 }

2. GET /api/dataextractions/getExtractionStatus?taskId=12345&key=...
   → poll until destinationFileUri is populated

3. GET <destinationFileUri>
   → download the result file
```

The `CordisClient` handles all of this automatically with a live progress bar.

---

## Output

Results are saved to the `data/` directory:

```
data/heidelberg_erc_20250619_143022.csv
```

The CSV/XLSX/JSON contains one row per project with all available CORDIS fields (title, acronym, funding, start/end date, status, coordinator, etc.).

---

## Extending

### Add a new pre-built query

Edit `src/query_builder.py` and add a new function:

```python
def build_my_query() -> str:
    return build_custom_query(
        content_type="project",
        programme_codes=["HORIZON.2.1"],
        organisations=[{"legalName": "MY UNIVERSITY"}],
    )
```

### Parse new formats

Add a parser in `src/data_processor.py` → `parse_response()`.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client |
| `python-dotenv` | `.env` file support |
| `pandas` | DataFrame, analytics, export |
| `openpyxl` | Excel (.xlsx) read/write |
| `rich` | Terminal output, progress bars, tables |
| `click` | CLI framework |

---

## Future Plans

- [ ] Interactive dashboard (Streamlit / Dash)
- [ ] Time-series funding analysis
- [ ] Network graph of collaborating institutions
- [ ] SQLite / DuckDB local caching
- [ ] Automated scheduled queries
