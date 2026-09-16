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

# Second line of defence: a materially shrunken site must never overwrite a
# larger one. A blocked crawl (DramaBox returns 403 to datacentre IPs) yields a
# valid-looking site with thousands of pages missing; publishing it took the
# live sitemap from 3,984 URLs to 862 in a single GitHub Actions run. The
# crawler refuses first; this catches anything that still slips through, such as
# a stale or partially-written snapshot.
count_urls() {
  # Count occurrences, not matching lines: the sitemap happens to put each
  # <url> on its own line today, but that is a formatting coincidence and
  # `grep -c` would silently undercount the moment it changed. Also note
  # `grep -c` prints 0 and exits 1 on no match, so a bare "|| echo 0" would
  # emit "0\n0" and break the arithmetic test.
  n=$(grep -o "<url>" "$1" 2>/dev/null | wc -l | tr -d ' ')
  echo "${n:-0}"
}

NEW_COUNT=$(count_urls site/sitemap.xml)
PREV_COUNT=$(
  curl -s --max-time 20 "https://${SITE_DOMAIN:-dramaindex.lol}/sitemap.xml" 2>/dev/null \
    | grep -o "<url>" | wc -l | tr -d ' '
)
PREV_COUNT=${PREV_COUNT:-0}

# Publishing an empty sitemap would de-list the whole site from search engines.
if [ "$NEW_COUNT" -eq 0 ]; then
  echo "" >&2
  echo "REFUSING TO DEPLOY: site/sitemap.xml has no <url> entries. That almost" >&2
  echo "certainly means the build failed or produced nothing." >&2
  exit 1
fi

if [ "$NEW_COUNT" -gt 0 ] && [ "$PREV_COUNT" -gt 0 ] \
   && [ "$NEW_COUNT" -lt $(( PREV_COUNT * 7 / 10 )) ]; then
  echo "" >&2
  echo "REFUSING TO DEPLOY: the new site has $NEW_COUNT URLs but the live site" >&2
  echo "has $PREV_COUNT - a drop that large means the crawl was blocked or" >&2
  echo "partial, not that the catalogue shrank." >&2
  if [ "${DRAMADB_FORCE_DEPLOY:-}" != "1" ]; then
    echo "Set DRAMADB_FORCE_DEPLOY=1 if the reduction is genuinely intended." >&2
    exit 1
  fi
  echo "DRAMADB_FORCE_DEPLOY=1 set; continuing anyway." >&2
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
