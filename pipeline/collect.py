#!/usr/bin/env python3
"""
Short-drama catalog collector.

Sources (all public, all permitted by robots.txt):
  - ReelShort shelf pages   -> embedded __NEXT_DATA__ catalog JSON
  - DramaBox home page      -> embedded __NEXT_DATA__ catalog JSON
  - Apple App Store RSS     -> public top-free / top-grossing charts

Design notes:
  * One HTTP request per shelf, cached to disk with a date stamp so a rerun on the
    same day is free and the trend logic has something to diff against.
  * Serial requests with a delay; this is a small polite crawl, not a scraper farm.
  * We store only metadata that is already public on the page. No video, no
    paywalled chapter bodies, no logged-in endpoints.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
SNAPS = OUT / "snapshots"
HISTORY = OUT / "history"

# The full snapshot is ~3.7 MB, most of it synopsis text and cover URLs. Those
# are catalogue fields: they are re-fetched every run and are already public on
# the platform. What cannot be re-fetched is the movement - yesterday's shelf
# rank and read count are gone once the platform updates. So the two are stored
# separately: the fat catalogue snapshot stays on whichever machine ran the
# crawl (and is not committed), while a narrow trend series is committed and
# accumulates across runs. Committing the full snapshot would add ~1.3 GB/year
# to the repository; the trend series is ~17 MB/year.
TREND_FIELDS = {
    "reelshort": ("shelf_rank", "read_count", "collect_count", "chapter_count"),
    "dramabox": ("rank", "view_count", "follow_count", "chapter_count"),
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# ReelShort shelf ids discovered from the homepage. Slugs are cosmetic; the id
# is what the page actually keys on, but we send the full path to be safe.
REELSHORT_SHELVES = {
    "top": "top-short-movies-dramas-51002892",
    "new_release": "new-release-short-movies-dramas-51002891",
    "reel_original": "reel-original-short-movies-dramas-51002893",
    "hidden_identity": "hidden-identity-short-movies-dramas-51002894",
    "love_at_first_sight": "love-at-first-sight-short-movies-dramas-51002895",
    "second_chance": "second-chance-short-movies-dramas-51002896",
    "pregnancy_babies": "pregnancy-babies-short-movies-dramas-51002897",
    "interactives": "reelshort-interactives-short-movies-dramas-51002898",
    "young_love": "young-love-short-movies-dramas-51002899",
    "reeltalk": "reeltalk-short-movies-dramas-51002900",
}

# DramaBox browse categories (ids read off the homepage nav). Each paginates
# via ?pageNo=N; we stop when a page returns no new rows.
DRAMABOX_CATEGORIES = [
    160, 161, 184, 189, 204, 248, 249, 251, 253, 254, 258, 259, 260, 261,
    263, 265, 266, 267, 269, 273, 275, 276, 291, 563, 583,
]
DRAMABOX_MAX_PAGES = 25

APPSTORE_CHARTS = {
    "us_ent_free": "https://itunes.apple.com/us/rss/topfreeapplications/limit=200/genre=6016/json",
    "us_ent_grossing": "https://itunes.apple.com/us/rss/topgrossingapplications/limit=200/genre=6016/json",
}

# Apps we treat as short-drama platforms when reading the store charts. Matched
# case-insensitively against the app name.
DRAMA_APP_MARKERS = (
    "reelshort", "dramabox", "shortmax", "dramawave", "netshort", "goodshort",
    "joyreels", "pinedrama", "blinkdrama", "storyreel", "vibeshort", "buzzreels",
    "soda reels", "reelife", "dramashorts", "shorttv", "flickreels", "melolo",
)

DELAY_SECONDS = 1.5


def fetch(url: str, cache_key: str, *, force: bool = False, retries: int = 3) -> str:
    """Fetch a URL, caching the body under data/raw/<date>/<key>.html.gz."""
    day = date.today().isoformat()
    cache_dir = RAW / day
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{cache_key}.gz"

    if cache_file.exists() and not force:
        with gzip.open(cache_file, "rt", encoding="utf-8") as fh:
            return fh.read()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/json,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            with gzip.open(cache_file, "wt", encoding="utf-8") as fh:
                fh.write(body)
            time.sleep(DELAY_SECONDS)
            return body
        except urllib.error.HTTPError as exc:
            print(f"  ! HTTP {exc.code} for {url}", file=sys.stderr)
            return ""
        except Exception as exc:  # noqa: BLE001 - network flake, retry then give up
            if attempt == retries:
                print(
                    f"  ! {type(exc).__name__} for {url} after {retries} tries: {exc}",
                    file=sys.stderr,
                )
                return ""
            time.sleep(DELAY_SECONDS * attempt)
    return ""


def next_data(html: str) -> dict:
    """Pull the Next.js __NEXT_DATA__ JSON payload out of a page."""
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S
    )
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def norm_title(title: str) -> str:
    """Normalize a title for cross-platform matching."""
    t = title.lower().strip()
    t = re.sub(r"[\u2018\u2019\u201c\u201d]", "'", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def collect_reelshort() -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for shelf, slug in REELSHORT_SHELVES.items():
        html = fetch(
            f"https://www.reelshort.com/shelf/{slug}", f"rs_{shelf}"
        )
        if not html:
            continue
        data = next_data(html)
        items = data.get("props", {}).get("pageProps", {}).get("list", [])
        for rank, item in enumerate(items, start=1):
            book_id = item.get("book_id")
            if not book_id or book_id in seen:
                continue
            seen.add(book_id)
            rows.append(
                {
                    "platform": "reelshort",
                    "platform_id": book_id,
                    "title": (item.get("book_title") or "").strip(),
                    "norm_title": norm_title(item.get("book_title") or ""),
                    "description": (item.get("special_desc") or "").strip(),
                    "cover": item.get("book_pic") or item.get("default_pic") or "",
                    "chapter_count": item.get("chapter_count"),
                    "read_count": item.get("read_count"),
                    "collect_count": item.get("collect_count"),
                    "lang": item.get("lang"),
                    "paid_start_chapter": item.get("paid_start"),
                    "has_trailer": bool(item.get("have_trailer")),
                    "themes": item.get("theme") or [],
                    "shelf": shelf,
                    "shelf_rank": rank,
                }
            )
        print(f"  reelshort/{shelf}: {len(items)} rows (total unique {len(seen)})")
    return rows


def _dramabox_row(item: dict, *, source: str, category: str = "", rank: int = 0) -> dict | None:
    book_id = str(item.get("bookId") or "")
    if not book_id:
        return None
    tags = item.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    labels = item.get("labels") or []
    if isinstance(labels, str):
        labels = [labels]
    return {
        "platform": "dramabox",
        "platform_id": book_id,
        "original_id": str(item.get("originalBookId") or ""),
        "title": (item.get("bookName") or "").strip(),
        "norm_title": norm_title(item.get("bookName") or ""),
        "description": (item.get("introduction") or "").strip(),
        "cover": item.get("cover") or "",
        "author": (item.get("author") or "").strip(),
        "view_count": item.get("viewCount"),
        "follow_count": item.get("followCount"),
        "rating": item.get("ratings"),
        "chapter_count": item.get("chapterCount"),
        "tags": tags,
        "labels": labels,
        "genres": item.get("typeOneNames") or [],
        "subgenres": item.get("typeTwoNames") or [],
        "source": source,
        "category": category,
        "rank": rank,
    }


def collect_dramabox() -> list[dict]:
    rows: dict[str, dict] = {}

    # Homepage blocks.
    html = fetch("https://www.dramabox.com/", "db_home")
    if html:
        page = next_data(html).get("props", {}).get("pageProps", {})
        items = list(page.get("bigList") or [])
        for block in page.get("smallData") or []:
            items.extend(block.get("items") or [])
        for rank, item in enumerate(items, start=1):
            row = _dramabox_row(item, source="home", rank=rank)
            if row and row["platform_id"] not in rows:
                rows[row["platform_id"]] = row
        print(f"  dramabox/home: {len(rows)} unique")

    # Category browse pages. Pagination is a path segment (/browse/<cat>/<page>),
    # not a query param - ?pageNo=N is ignored and silently returns page 1.
    for cat in DRAMABOX_CATEGORIES:
        cat_name = ""
        for page_no in range(1, DRAMABOX_MAX_PAGES + 1):
            url = f"https://www.dramabox.com/browse/{cat}"
            if page_no > 1:
                url += f"/{page_no}"
            body = fetch(url, f"db_cat{cat}_p{page_no}")
            if not body:
                break
            page = next_data(body).get("props", {}).get("pageProps", {})
            books = page.get("bookList") or []
            if not books:
                break
            if not cat_name:
                cat_name = page.get("typeTwoName") or page.get("typeOneName") or str(cat)
            added = 0
            for rank, item in enumerate(books, start=1):
                row = _dramabox_row(
                    item, source="browse", category=cat_name, rank=rank
                )
                if row and row["platform_id"] not in rows:
                    rows[row["platform_id"]] = row
                    added += 1
            if added == 0:
                break
        print(f"  dramabox/browse/{cat} ({cat_name}): running total {len(rows)}")

    print(f"  dramabox total: {len(rows)} rows")
    return list(rows.values())


def collect_appstore() -> list[dict]:
    rows: list[dict] = []
    for chart, url in APPSTORE_CHARTS.items():
        body = fetch(url, chart)
        if not body:
            continue
        try:
            feed = json.loads(body)["feed"]
        except (json.JSONDecodeError, KeyError):
            continue
        entries = feed.get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        for rank, entry in enumerate(entries, start=1):
            name = entry.get("im:name", {}).get("label", "")
            if not any(m in name.lower() for m in DRAMA_APP_MARKERS):
                continue
            rows.append(
                {
                    "chart": chart,
                    "rank": rank,
                    "name": name,
                    "developer": entry.get("im:artist", {}).get("label", ""),
                    "app_id": entry.get("id", {}).get("attributes", {}).get("im:id", ""),
                    "url": entry.get("id", {}).get("label", ""),
                }
            )
        print(f"  appstore/{chart}: {len(entries)} entries, {sum(1 for r in rows if r['chart']==chart)} drama apps")
    return rows


def write_trend_history(snapshot: dict) -> Path:
    """Write the small, committable trend series for this day.

    One gzipped JSON file per day, holding only the values that change and
    cannot be recovered later. Unchanged from the full snapshot in meaning, and
    a superset of what the site needs to diff day over day.
    """
    trend = {
        "date": snapshot.get("date"),
        "collected_at": snapshot.get("collected_at"),
    }
    for pf, fields in TREND_FIELDS.items():
        rows = {}
        for row in snapshot.get(pf, []):
            pid = row.get("platform_id")
            if not pid:
                continue
            rows[pid] = [row.get(f) for f in fields]
        trend[pf] = rows
        trend[f"{pf}_fields"] = list(fields)

    trend["appstore"] = [
        {k: a.get(k) for k in ("chart", "rank", "name", "app_id")}
        for a in snapshot.get("appstore", [])
    ]

    HISTORY.mkdir(parents=True, exist_ok=True)
    path = HISTORY / f"{snapshot['date']}.json.gz"
    raw = json.dumps(trend, ensure_ascii=False, separators=(",", ":")).encode()
    path.write_bytes(gzip.compress(raw, 9))
    return path


# A crawl that returns far fewer rows than the last good run is a failure, not a
# smaller catalogue. DramaBox returns 403 to datacentre IP ranges (GitHub
# Actions among them), which yields a complete-but-empty result rather than an
# exception - so without this check a blocked crawl would publish a site with
# thousands of pages silently deleted. Raise when today's count drops below this
# fraction of the previous snapshot.
MIN_COVERAGE = 0.7


def previous_counts() -> dict[str, int]:
    """Row counts from the most recent snapshot, for the coverage check."""
    files = sorted(SNAPS.glob("*.json"))
    for f in reversed(files):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        counts = {pf: len(d.get(pf, [])) for pf in TREND_FIELDS}
        if any(counts.values()):
            return counts
    return {}


def check_coverage(snapshot: dict) -> list[str]:
    """Return a list of human-readable problems; empty means the crawl is sane."""
    prev = previous_counts()
    problems = []
    for pf in TREND_FIELDS:
        got = len(snapshot.get(pf, []))
        was = prev.get(pf, 0)
        if was and got < was * MIN_COVERAGE:
            problems.append(
                f"{pf}: {got} rows, down from {was} "
                f"({got/was:.0%} of previous, floor is {MIN_COVERAGE:.0%})"
            )
        elif not was and got == 0:
            problems.append(f"{pf}: 0 rows and no previous snapshot to compare")
    return problems


def main() -> int:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"collecting at {stamp}")

    print("ReelShort:")
    reelshort = collect_reelshort()
    print("DramaBox:")
    dramabox = collect_dramabox()
    print("App Store:")
    appstore = collect_appstore()

    snapshot = {
        "collected_at": stamp,
        "date": date.today().isoformat(),
        "reelshort": reelshort,
        "dramabox": dramabox,
        "appstore": appstore,
    }

    # Refuse to write anything if the crawl came back materially incomplete.
    # Writing a partial snapshot is worse than writing none: build_site.py would
    # render a site missing thousands of pages, deploy.sh would publish it, and
    # IndexNow would push the shrunken URL set to search engines - which is
    # exactly what one GitHub Actions run did before this guard existed.
    problems = check_coverage(snapshot)
    if problems:
        print("\nREFUSING TO PUBLISH - crawl looks incomplete:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "  Most likely cause for a datacentre runner is a 403/WAF block "
            "on the origin. Leaving existing data untouched.",
            file=sys.stderr,
        )
        return 2

    SNAPS.mkdir(parents=True, exist_ok=True)
    snap_file = SNAPS / f"{date.today().isoformat()}.json"
    snap_file.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    hist_file = write_trend_history(snapshot)

    print(
        f"\nwrote {snap_file}\n"
        f"  reelshort={len(reelshort)} dramabox={len(dramabox)} appstore={len(appstore)}"
    )
    print(
        f"trend history {hist_file} ({hist_file.stat().st_size/1024:.0f} KB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
