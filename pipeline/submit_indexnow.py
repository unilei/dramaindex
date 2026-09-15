#!/usr/bin/env python3
"""
Submit the site's URLs to IndexNow after a build.

IndexNow is a shared endpoint (Bing, Yandex, Seznam, Naver) that accepts URL
submissions without an account, provided ownership is proven by hosting
<key>.txt at the site root. Submitting after each daily build means new and
changed pages get discovered on their own rather than waiting for a crawl.

Silently does nothing when DRAMADB_INDEXNOW_KEY is unset.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH = 2000
MAX_URLS = 10000  # IndexNow per-day ceiling


def main() -> int:
    key = os.environ.get("DRAMADB_INDEXNOW_KEY", "").strip()
    domain = os.environ.get("DRAMADB_DOMAIN", "").strip().rstrip("/")
    if not key:
        print("indexnow: no key set, skipping")
        return 0
    if not domain or "example.com" in domain:
        print("indexnow: no real domain set, skipping")
        return 0

    sitemap = SITE / "sitemap.xml"
    if not sitemap.exists():
        print("indexnow: no sitemap; run build_site.py first")
        return 1

    urls = re.findall(r"<loc>(.*?)</loc>", sitemap.read_text(encoding="utf-8"))
    if not urls:
        print("indexnow: sitemap has no urls")
        return 1
    urls = urls[:MAX_URLS]

    host = domain.split("/")[0]
    submitted = 0
    for i in range(0, len(urls), BATCH):
        chunk = urls[i : i + BATCH]
        payload = {
            "host": host,
            "key": key,
            "keyLocation": f"https://{domain}/{key}.txt",
            "urlList": chunk,
        }
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                print(f"indexnow: batch {i // BATCH + 1} -> {resp.status} ({len(chunk)} urls)")
                submitted += len(chunk)
        except urllib.error.HTTPError as exc:
            print(f"indexnow: batch {i // BATCH + 1} -> HTTP {exc.code}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - submission is best-effort
            print(f"indexnow: batch {i // BATCH + 1} -> {type(exc).__name__}", file=sys.stderr)

    print(f"indexnow: submitted {submitted} urls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
