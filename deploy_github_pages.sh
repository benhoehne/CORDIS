#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy_github_pages.sh – build dist/ and push to the gh-pages branch
#
# Run this whenever:
#   • You first set up GitHub Pages (creates the gh-pages branch)
#   • The SQLite database has been rebuilt and you want to publish it
#   • You want a one-shot full redeploy (HTML + JS + DB)
#
# After this script succeeds (first time), enable Pages in GitHub:
#   Settings → Pages → Source: Deploy from branch
#   Branch: gh-pages  /  Folder: / (root)  → Save
#
# Site URL: https://benhoehne.github.io/CORDIS/
#
# ⚠️  Note: cordis_heidelberg.db is ~57 MB. GitHub accepts files up to 100 MB,
#    but Git will print a warning above 50 MB. This is harmless for now.
#    If the DB grows beyond 100 MB, consider Git LFS or an external CDN.
#
# Usage:
#   ./deploy_github_pages.sh [--db /path/to/custom.db]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE_PATH="${TMPDIR:-/tmp}/cordis-gh-pages-$$"

# ── 1. Build the dist/ bundle (also regenerates standalone.html) ──────────────
echo "── Step 1/4: Building static bundle ────────────────────────────────────"
"${SCRIPT_DIR}/deploy_static.sh" "$@"

# ── 2. Prepare the gh-pages worktree ─────────────────────────────────────────
echo ""
echo "── Step 2/4: Preparing gh-pages branch ─────────────────────────────────"
cd "${SCRIPT_DIR}"

git worktree remove --force "${WORKTREE_PATH}" 2>/dev/null || true

if git show-ref --verify --quiet refs/heads/gh-pages; then
  echo "   gh-pages branch already exists – checking out"
  git worktree add "${WORKTREE_PATH}" gh-pages
else
  echo "   gh-pages branch not found – creating orphan branch"
  git worktree add --orphan "${WORKTREE_PATH}" gh-pages
fi

# ── 3. Copy dist/ into the worktree ──────────────────────────────────────────
echo ""
echo "── Step 3/4: Copying dist/ into gh-pages ────────────────────────────────"
cp "${SCRIPT_DIR}/dist/index.html"           "${WORKTREE_PATH}/index.html"
cp "${SCRIPT_DIR}/dist/app-standalone.js"    "${WORKTREE_PATH}/app-standalone.js"
cp "${SCRIPT_DIR}/dist/cordis_heidelberg.db" "${WORKTREE_PATH}/cordis_heidelberg.db"
touch "${WORKTREE_PATH}/.nojekyll"

# ── 4. Commit and push ────────────────────────────────────────────────────────
echo ""
echo "── Step 4/4: Committing and pushing ─────────────────────────────────────"
cd "${WORKTREE_PATH}"
git add -A

if git diff --cached --quiet; then
  echo "   Nothing changed on gh-pages – skipping commit."
else
  STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  git commit -m "Deploy static site ${STAMP}"
  git push origin gh-pages
  echo ""
  echo "✅  Pushed to gh-pages."
fi

cd "${SCRIPT_DIR}"
git worktree remove "${WORKTREE_PATH}"

echo ""
echo "────────────────────────────────────────────────────────────────────────"
echo "Next step (first-time only):"
echo "  GitHub → Settings → Pages"
echo "  Source: Deploy from branch"
echo "  Branch: gh-pages  /  Folder: / (root)  → Save"
echo ""
echo "Site URL: https://benhoehne.github.io/CORDIS/"
echo "────────────────────────────────────────────────────────────────────────"
