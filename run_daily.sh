#!/bin/sh
# Daily refresh: crawl, rebuild the site, report.
#
# This machine is the only crawler, by necessity rather than preference.
# DramaBox answers 403 to GitHub's runner IP ranges while returning 200 here,
# and DramaBox is 3,047 of the 3,866 series - so a runner-based crawl could only
# ever produce a catalogue missing ~79% of its pages. A GitHub Actions workflow
# was tried for this and removed for that reason.
#
# Why daily at all: the app-store chart history and shelf-rank movement are only
# meaningful as a time series. A single snapshot shows a catalogue; a series
# shows trends, and trends are the part nobody else is publishing.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"

# launchd runs with a minimal PATH, so resolve the interpreter explicitly
# rather than relying on `python3` being on it.
PY=/Users/lei/.pyenv/versions/3.12.6/bin/python3
[ -x "$PY" ] || PY=$(command -v python3)

TODAY=$(date -u '+%Y-%m-%d')

# A no-op when today's crawl already happened, so a manual re-run or a
# wake-from-sleep catch-up cannot overwrite a good snapshot with a second one.
if [ "${DRAMADB_SKIP_IF_DONE:-}" = "1" ] && [ -f "data/snapshots/$TODAY.json" ]; then
  echo "=== $(date '+%Y-%m-%d %H:%M:%S'): snapshot for $TODAY already exists, skipping ==="
  exit 0
fi

echo "=== dramadb daily run: $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "--- interpreter: $PY"

# collect.py exits non-zero without writing anything if the crawl came back
# materially incomplete, so a blocked or partial run stops here rather than
# propagating a shrunken catalogue to build, deploy and IndexNow.
"$PY" pipeline/collect.py
"$PY" pipeline/build_site.py

echo "--- drama pages: $(ls site/drama | wc -l | tr -d ' ')"
echo "--- genre hubs:  $(ls site/genre | wc -l | tr -d ' ')"

# Publish. Without this the crawl accumulates locally and the live site never
# changes, which defeats the point of running daily.
if [ -n "${DRAMADB_DOMAIN:-}" ]; then
  DRAMADB_DOMAIN="$DRAMADB_DOMAIN" "$HERE/deploy.sh"
  "$PY" pipeline/submit_indexnow.py || echo "--- indexnow submission failed (non-fatal)"
else
  echo "--- DRAMADB_DOMAIN not set; skipping deploy (site rebuilt locally only)"
fi

# Commit the trend series so it accumulates in the repo rather than living only
# on this machine. Scoped to data/history on purpose: an unscoped commit would
# sweep in whatever else happened to be staged in the working copy.
if [ "${DRAMADB_COMMIT_HISTORY:-}" = "1" ]; then
  if git diff --quiet -- data/history 2>/dev/null && \
     [ -z "$(git ls-files --others --exclude-standard data/history 2>/dev/null)" ]; then
    echo "--- no new trend history to commit"
  else
    git add -f data/history 2>/dev/null || true
    git -c user.name="dramaindex-bot" \
        -c user.email="dramaindex-bot@users.noreply.github.com" \
        commit -q -m "trend history $TODAY" -- data/history || true
    # Rebase before pushing: a manual commit from another machine would
    # otherwise reject the push and silently drop this day's series.
    git pull --rebase -q 2>/dev/null || true
    git push -q 2>/dev/null || echo "--- history push failed (non-fatal)"
    echo "--- trend history committed"
  fi
fi

echo "--- done"
