#!/bin/sh
# Daily refresh: crawl, rebuild the site, report.
#
# This is the BACKUP path. The primary scheduler is the GitHub Actions workflow
# (.github/workflows/daily-index.yml), which does not depend on this machine
# being on. launchd is kept because it has one property Actions does not: if the
# machine is asleep at the scheduled time, it runs the job on the next wake
# instead of skipping it, and a skipped day is trend history that cannot be
# recovered retroactively.
#
# DRAMADB_SKIP_IF_DONE=1 makes the run a no-op when today's snapshot already
# exists, so the two schedulers can coexist without crawling twice.
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

if [ "${DRAMADB_SKIP_IF_DONE:-}" = "1" ] && [ -f "data/snapshots/$TODAY.json" ]; then
  echo "=== $(date '+%Y-%m-%d %H:%M:%S'): snapshot for $TODAY already exists, skipping ==="
  exit 0
fi

echo "=== dramadb daily run: $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "--- interpreter: $PY"

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
# on this machine. Skipped silently when there is nothing new.
if [ "${DRAMADB_COMMIT_HISTORY:-}" = "1" ]; then
  git add -f data/history 2>/dev/null || true
  if git diff --cached --quiet 2>/dev/null; then
    echo "--- no new trend history to commit"
  else
    git -c user.name="dramaindex-bot" \
        -c user.email="dramaindex-bot@users.noreply.github.com" \
        commit -q -m "trend history $TODAY" && git push -q || \
        echo "--- history commit/push failed (non-fatal)"
  fi
fi

echo "--- done"
