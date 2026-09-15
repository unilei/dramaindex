#!/bin/sh
# Publish site/ to GitHub Pages.
#
# Uses a separate orphan gh-pages branch so the generated output never mixes
# with the source history. Rebuilds first so what ships always matches the
# latest snapshot.
#
#   ./deploy.sh                 # build with default domain, push
#   DRAMADB_DOMAIN=x.com ./deploy.sh
#
# Requires: git, and a remote already configured (see REPO below).

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"

PY=/Users/lei/.pyenv/versions/3.12.6/bin/python3
[ -x "$PY" ] || PY=$(command -v python3)

REPO="${DRAMADB_REPO:-$(git remote get-url origin 2>/dev/null || true)}"
if [ -z "$REPO" ]; then
  echo "No git remote 'origin'. Create the repo and add it first:" >&2
  echo "  gh repo create <name> --public --source=. --remote=origin" >&2
  exit 1
fi

echo "=== rebuilding site ==="
"$PY" pipeline/build_site.py

# A placeholder domain means sitemap.xml and robots.txt point at example.com,
# which would teach search engines the wrong host. Refuse to publish that.
if grep -q "example\.com" site/sitemap.xml 2>/dev/null; then
  echo "" >&2
  echo "REFUSING TO DEPLOY: site/sitemap.xml still contains the example.com" >&2
  echo "placeholder. Re-run with the real domain so sitemap and robots.txt are" >&2
  echo "correct, e.g.:" >&2
  echo "  DRAMADB_DOMAIN=yourdomain.com ./deploy.sh" >&2
  echo "Or, if deploying to a *.github.io URL, pass that host explicitly." >&2
  exit 1
fi

echo "=== publishing site/ to gh-pages ==="
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cp -R site/. "$TMP"/
cd "$TMP"
git init -q
git checkout -q -b gh-pages
git add -A
git -c user.name="dramadb-bot" -c user.email="dramadb@users.noreply.github.com" \
    commit -q -m "Publish $(date '+%Y-%m-%d %H:%M')"
git push -q --force "$REPO" gh-pages

echo "=== deployed ==="
echo "  files: $(find . -name '*.html' | wc -l | tr -d ' ') html pages"
echo "  Pages URL: check Settings > Pages in the repo (source: gh-pages branch)"
