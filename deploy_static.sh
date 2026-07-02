#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy_static.sh – build and assemble the deployable static bundle
#
# Output layout (dist/):
#   dist/
#     index.html              ← generated standalone.html (sql.js + Tailwind)
#     app-standalone.js       ← standalone JS referenced by index.html
#     cordis_heidelberg.db    ← SQLite database fetched by the browser
#
# Usage:
#   ./deploy_static.sh [--db /path/to/custom.db] [--out /path/to/output]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DB="${SCRIPT_DIR}/data/cordis_heidelberg.db"
DEFAULT_OUT="${SCRIPT_DIR}/dist"

DB_PATH="${DEFAULT_DB}"
OUT_DIR="${DEFAULT_OUT}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)   DB_PATH="$2"; shift 2 ;;
    --out)  OUT_DIR="$2"; shift 2 ;;
    *)      echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ ! -f "${DB_PATH}" ]]; then
  echo "❌  Database not found: ${DB_PATH}"
  echo "    Run the ETL pipeline first (python manage.py build) or pass --db <path>."
  exit 1
fi

# ── Step 1: Generate standalone.html from index.html ──────────────────────────
echo "→  Generating standalone.html from index.html…"
python3 "${SCRIPT_DIR}/build_standalone.py"

# ── Step 2: Assemble dist/ ─────────────────────────────────────────────────────
echo "→  Cleaning output dir: ${OUT_DIR}"
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

STATIC="${SCRIPT_DIR}/src/web/static"

echo "→  Copying standalone.html → dist/index.html"
cp "${STATIC}/standalone.html" "${OUT_DIR}/index.html"

echo "→  Copying app-standalone.js → dist/"
cp "${STATIC}/app-standalone.js" "${OUT_DIR}/app-standalone.js"

echo "→  Copying database ($(du -sh "${DB_PATH}" | cut -f1)) → dist/cordis_heidelberg.db"
cp "${DB_PATH}" "${OUT_DIR}/cordis_heidelberg.db"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "✅  Static bundle ready in: ${OUT_DIR}/"
ls -lh "${OUT_DIR}"
echo ""
echo "To preview locally:"
echo "    cd \"${OUT_DIR}\" && python -m http.server 8080"
echo "    then open http://localhost:8080"
echo ""
echo "Note: Opening index.html as a file:// URL will not work (CORS on fetch)."
echo "      Always use a local HTTP server for testing."
