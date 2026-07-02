#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy_static.sh – assemble a deployable static bundle
#
# Output layout (dist/):
#   dist/
#     index.html              ← standalone browser app (sql.js + Tailwind)
#     cordis_heidelberg.db    ← SQLite database fetched by the browser
#
# The two files can be served by any static host:
#   • Nginx / Apache:  point DocumentRoot at dist/
#   • GitHub Pages:    push dist/ contents to gh-pages branch
#   • Python quick-test:  cd dist && python -m http.server 8080
#
# Usage:
#   ./deploy_static.sh [--db /path/to/custom.db] [--out /path/to/output]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DB="${SCRIPT_DIR}/data/cordis_heidelberg.db"
DEFAULT_OUT="${SCRIPT_DIR}/dist"

DB_PATH="${DEFAULT_DB}"
OUT_DIR="${DEFAULT_OUT}"

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)   DB_PATH="$2"; shift 2 ;;
    --out)  OUT_DIR="$2"; shift 2 ;;
    *)      echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Validate inputs ───────────────────────────────────────────────────────────
if [[ ! -f "${DB_PATH}" ]]; then
  echo "❌  Database not found: ${DB_PATH}"
  echo "    Run the ETL pipeline first (python manage.py build) or pass --db <path>."
  exit 1
fi

# ── Build ─────────────────────────────────────────────────────────────────────
echo "→  Cleaning output dir: ${OUT_DIR}"
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

echo "→  Copying standalone HTML → dist/index.html"
cp "${SCRIPT_DIR}/src/web/static/standalone.html" "${OUT_DIR}/index.html"

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
echo "Note: The browser must be able to fetch cordis_heidelberg.db via HTTP."
echo "      Opening index.html directly as a file:// URL will not work due to"
echo "      CORS restrictions on fetch(). Use a local HTTP server for testing."
