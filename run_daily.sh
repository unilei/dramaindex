#!/bin/sh
# Daily refresh: crawl, rebuild the site, report.
# Intended to be run by cron once a day. Example crontab entry (09:20 daily):
#   20 9 * * * /Users/lei/ZCodeProject/zzzzzzz/dramadb/run_daily.sh >> /tmp/dramadb.log 2>&1
#
# Why daily: the app-store chart history and shelf-rank movement are only
# meaningful as a time series. A single snapshot shows a catalogue; a series
# shows trends, and trends are the part nobody else is publishing.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"

# launchd runs with a minimal PATH, so resolve the interpreter explicitly
# rather than relying on `python3` being on it.
PY=/Users/lei/.pyenv/versions/3.12.6/bin/python3
[ -x "$PY" ] || PY=$(command -v python3)

echo "=== dramadb daily run: $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "--- interpreter: $PY"

"$PY" pipeline/collect.py
"$PY" pipeline/build_site.py

echo "--- drama pages: $(ls site/drama | wc -l | tr -d ' ')"
echo "--- genre hubs:  $(ls site/genre | wc -l | tr -d ' ')"
echo "--- done"
