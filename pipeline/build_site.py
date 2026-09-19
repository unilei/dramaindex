#!/usr/bin/env python3
"""
Build the static site from collected snapshots.

Output: dramadb/site/ containing
  index.html              - trending board (cross-platform)
  drama/<slug>.html       - one page per drama (SEO target)
  genre/<slug>.html       - genre hubs
  charts.html             - app store chart history
  sitemap.xml, robots.txt
  data/*.json             - machine-readable feeds

Everything is plain HTML - no JS framework - because many AI crawlers and a
meaningful slice of human visitors do not execute JavaScript.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
from collections import defaultdict
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data" / "snapshots"
HISTORY_DIR = ROOT / "data" / "history"
ASSETS = ROOT / "assets"
OUT = ROOT / "site"

SITE_NAME = "DramaIndex"
SITE_TAGLINE = "The short-drama database"

# Set SITE_DOMAIN (or env DRAMADB_DOMAIN) once a domain is live so sitemap and
# robots.txt emit absolute URLs. Until then we emit a clearly-marked placeholder
# rather than silently shipping a wrong canonical host.
SITE_DOMAIN = os.environ.get("DRAMADB_DOMAIN", "example.com").rstrip("/")
SITE_SCHEME = "https"

# SITE_DOMAIN may carry a path (unilei.github.io/dramaindex); the host is what
# a CNAME file needs. GitHub Pages serves a custom domain only when a CNAME
# naming that host sits at the site root, and build_site.py wipes site/ on
# every run, so it has to be emitted here - a CNAME added by hand in the repo
# would silently vanish at the next daily build and drop the domain.
SITE_HOST = SITE_DOMAIN.split("/", 1)[0]
CUSTOM_DOMAIN = ""
if SITE_HOST and SITE_HOST != "example.com" and not SITE_HOST.endswith(".github.io"):
    CUSTOM_DOMAIN = SITE_HOST

# IndexNow key: hosting <key>.txt at the site root proves domain ownership so
# search engines accept bulk URL submissions without an account. Generated
# once and kept stable; changing it invalidates prior submissions.
INDEXNOW_KEY = os.environ.get("DRAMADB_INDEXNOW_KEY", "").strip()

# Search-console verification files, as "filename:contents" pairs. Kept in the
# generator because build_site.py wipes site/ on every run, so a file dropped
# in by hand would silently vanish at the next daily build and un-verify the
# property. Comma-separated for multiple consoles.
SITE_VERIFICATION_FILES = [
    pair.split(":", 1)
    for pair in os.environ.get("DRAMADB_VERIFY_FILES", "").split(",")
    if ":" in pair
]

# Referral/affiliate base URLs. Left blank until the affiliate account exists;
# blank means outbound links are plain (non-monetised) links, which keeps the
# site honest while the affiliate application is pending.
REFERRAL_LINKS: dict[str, str] = {
    # RS Boost referral link, verified 2026-09-16: 302s with attribution params
    # (distribute_uid=17435) then lands on the App Store listing.
    #
    # This short code is bound to ONE series. Its redirect carries
    # parm1=<book id> (Salt Kiss) and that parameter is applied server-side, so
    # appending or overriding parm1 here does NOT change the landing series -
    # verified by hand-building the AppsFlyer onelink URL, which returns 200
    # without redirecting because the signature is minted server-side. Only the
    # RS Boost resource-square can create a per-series code. So the link is
    # labelled for what it actually does (see watch_label) rather than promised
    # as "watch this series", which would lose the click on arrival.
    "reelshort": "https://reelslink.com/cps/cR6hNQ",
}

PLATFORM_LABELS = {
    "reelshort": "ReelShort",
    "dramabox": "DramaBox",
}

# Shelf ids are internal slugs; printing them raw produced sentences like
# "Ranks #192 of 245 in top", which reads as broken English. Category names from
# DramaBox are already human-readable, so only these need mapping.
SHELF_LABELS = {
    "top": "the overall chart",
    "new_release": "new releases",
    "reel_original": "ReelShort Originals",
    "hidden_identity": "Hidden Identity",
    "love_at_first_sight": "Love at First Sight",
    "second_chance": "Second Chance",
    "pregnancy_babies": "Pregnancy & Babies",
    "interactives": "Interactives",
    "young_love": "Young Love",
    "reeltalk": "ReelTalk",
}

# "all" is a browse bucket rather than a genre, so ranking inside it would claim
# a category the reader cannot picture.
SKIP_GROUPS = {"all"}

# Header mark, inlined rather than loaded as a file: it is 300 bytes, saves a
# request on every one of ~4,500 pages, and keeps the header rendering even if
# the image fails. Geometry mirrors assets/favicon.ico (play triangle plus three
# index bars) so the tab icon and the header read as the same mark.
LOGO_SVG = (
    '<svg class="mark" viewBox="0 0 32 32" width="20" height="20" '
    'aria-hidden="true" focusable="false">'
    '<rect width="32" height="32" rx="7" fill="#0d0f14" stroke="#242a37"/>'
    '<path d="M9 8.5v15l13-7.5z" fill="#ff4d6d"/>'
    '<rect x="20.5" y="9" width="6" height="2.6" rx="1.3" fill="#8b95a8"/>'
    '<rect x="20.5" y="14.7" width="6" height="2.6" rx="1.3" fill="#e8ecf3"/>'
    '<rect x="20.5" y="20.4" width="6" height="2.6" rx="1.3" fill="#8b95a8"/>'
    "</svg>"
)

PLATFORM_URLS = {
    "reelshort": "https://www.reelshort.com/",
    "dramabox": "https://www.dramabox.com/",
}

# Platforms whose referral link opens the app but cannot be pointed at a chosen
# series, so the call to action must not claim the series is what opens.
SERIES_LOCKED_REFERRALS = {"reelshort"}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:80] or "untitled"


def load_snapshots() -> list[dict]:
    """Catalogue snapshots: the full records the pages are rendered from.

    These are large and machine-local (they hold synopsis text and cover URLs,
    which are re-fetched on every crawl). On a fresh checkout - a GitHub Actions
    runner, say - none exist, so callers must tolerate an empty list and fall
    back to the committed trend series for anything that has to survive.
    """
    snaps = []
    for f in sorted(SNAP_DIR.glob("*.json")):
        try:
            snaps.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return snaps


def load_history() -> list[dict]:
    """Committed trend series, oldest first: one small gzipped file per day.

    This is the only part of the crawl that is committed, because it is the only
    part that cannot be re-derived - a platform's rank and read count for a past
    day are gone once it updates. The catalogue can always be re-fetched; this
    cannot.
    """
    out = []
    for f in sorted(HISTORY_DIR.glob("*.json.gz")):
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                out.append(json.load(fh))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def history_deltas(history: list[dict]) -> dict[str, dict]:
    """Per-series change between the two most recent days.

    Returns {platform:series_id: {...}} with the raw previous and current values
    plus a signed delta for each tracked metric. Empty when there is only one
    day, which is the honest answer: a single day has no movement to report.
    """
    if len(history) < 2:
        return {}
    prev, cur = history[-2], history[-1]
    out: dict[str, dict] = {}
    for pf in ("reelshort", "dramabox"):
        fields = cur.get(f"{pf}_fields") or prev.get(f"{pf}_fields") or []
        prev_rows = prev.get(pf) or {}
        for pid, vals in (cur.get(pf) or {}).items():
            old = prev_rows.get(pid)
            if old is None:
                out.setdefault(pf, {})[pid] = {"new": True}
                continue
            changes = {}
            for i, name in enumerate(fields):
                a = old[i] if i < len(old) else None
                b = vals[i] if i < len(vals) else None
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    changes[name] = {"prev": a, "cur": b, "delta": b - a}
            if changes:
                out.setdefault(pf, {})[pid] = changes
    return out


def excerpt(text: str, limit: int = 200) -> str:
    """Short quoted excerpt of a platform synopsis, cut on a word boundary.

    We deliberately do not reproduce the full synopsis. Publishing the complete
    text of thousands of copyrighted descriptions is a redistribution problem,
    not an indexing one; a short excerpt for identification plus a link to the
    source is the defensible version.
    """
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:") + "\u2026"


def outbound_url(platform: str) -> str:
    """Referral URL when one is configured, otherwise the plain platform URL."""
    return REFERRAL_LINKS.get(platform) or PLATFORM_URLS.get(platform, "#")


def watch_label(platform: str, title: str) -> str:
    """Call-to-action text that matches what the link actually does.

    The referral short code is bound server-side to one fixed series, and the
    binding cannot be overridden from here (see REFERRAL_LINKS). So on any other
    series page, naming that series in the button would be a promise the link
    cannot keep - the visitor arrives on a different show and leaves. The label
    therefore only claims what is true: the app opens. It deliberately does not
    repeat the page's own title back at the reader.
    """
    if platform in SERIES_LOCKED_REFERRALS:
        return "Open the ReelShort app"
    return f"Watch on {escape(PLATFORM_LABELS.get(platform, platform))}"


def norm_title(text: str) -> str:
    """Loose title key for matching the same series across platforms."""
    t = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    t = re.sub(r"\b(the|a|an|my|of|and|to|in|for|with)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def affiliate_note(platform: str) -> str:
    """Disclosure shown next to outbound links, but only when they earn."""
    if platform not in REFERRAL_LINKS:
        return ""
    return (
        '<p style="font-size:11.5px;color:var(--mut);margin-top:6px">'
        "Referral link &mdash; we may earn a commission at no extra cost to you.</p>"
    )


def fmt_num(n) -> str:
    if n is None:
        return "-"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{n:,}"


def merge(snapshots: list[dict]) -> dict:
    """Merge all snapshots into one record set, keeping first-seen and last-seen."""
    dramas: dict[str, dict] = {}
    for snap in snapshots:
        day = snap.get("date", "")
        for row in snap.get("reelshort", []):
            key = f"reelshort:{row['platform_id']}"
            rec = dramas.setdefault(
                key,
                {
                    **row,
                    "first_seen": day,
                    "last_seen": day,
                    "shelf_history": [],
                },
            )
            rec["last_seen"] = day
            rec.update({k: v for k, v in row.items() if v not in (None, "", [])})
            if row.get("shelf") and row.get("shelf_rank"):
                rec["shelf_history"].append(
                    {"date": day, "shelf": row["shelf"], "rank": row["shelf_rank"]}
                )
        for row in snap.get("dramabox", []):
            key = f"dramabox:{row['platform_id']}"
            rec = dramas.setdefault(
                key,
                {
                    **row,
                    "first_seen": day,
                    "last_seen": day,
                    "shelf_history": [],
                },
            )
            rec["last_seen"] = day
            rec.update({k: v for k, v in row.items() if v not in (None, "", [])})
    return dramas


CSS = """
:root{--bg:#0d0f14;--card:#161a23;--line:#242a37;--tx:#e8ecf3;--mut:#8b95a8;
--acc:#ff4d6d;--acc2:#5b8cff;--ok:#3ddc97}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--acc2);text-decoration:none}a:hover{text-decoration:underline}
header{border-bottom:1px solid var(--line);padding:14px 20px;display:flex;
gap:20px;align-items:center;flex-wrap:wrap;position:sticky;top:0;
background:rgba(13,15,20,.95);backdrop-filter:blur(8px);z-index:10}
.logo{font-weight:700;font-size:18px;color:var(--tx);display:inline-flex;
align-items:center;gap:8px}
.logo .mark{display:block;flex:none}
.logo span{color:var(--acc)}
nav a{color:var(--mut);margin-right:14px;font-size:14px}
main{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:19px;margin:32px 0 12px;border-left:3px solid var(--acc);padding-left:10px}
.sub{color:var(--mut);font-size:14px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
overflow:hidden;transition:border-color .15s}
.card:hover{border-color:var(--acc)}
.card img{width:100%;aspect-ratio:2/3;object-fit:cover;display:block;background:#0a0c10}
.card .body{padding:10px 11px 12px}
.card .t{font-weight:600;font-size:13.5px;line-height:1.35;display:block;
color:var(--tx);min-height:37px}
.pf{display:inline-block;font-size:10.5px;padding:2px 7px;border-radius:20px;
background:#232a38;color:var(--mut);margin-top:7px;text-transform:uppercase;
letter-spacing:.4px}
.pf.reelshort{background:#3a1b2b;color:#ff8fa8}
.pf.dramabox{background:#1b2b3a;color:#8fc4ff}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;
letter-spacing:.5px}
tr:hover td{background:#131720}
.rank{color:var(--mut);font-variant-numeric:tabular-nums;width:42px}
.pill{display:inline-block;font-size:11px;padding:2px 9px;border-radius:20px;
background:#232a38;color:var(--mut);margin:0 5px 5px 0}
.meta{display:flex;gap:22px;flex-wrap:wrap;margin:14px 0 20px;font-size:14px}
.meta div b{display:block;color:var(--mut);font-size:11.5px;text-transform:uppercase;
letter-spacing:.5px;font-weight:600}
.note{background:#161a23;border:1px solid var(--line);border-left:3px solid var(--acc2);
border-radius:8px;padding:12px 15px;font-size:13.5px;color:var(--mut);margin:20px 0}
.detail{display:grid;grid-template-columns:230px 1fr;gap:26px;align-items:start}
.detail img{width:100%;border-radius:10px;border:1px solid var(--line)}
@media(max-width:640px){.detail{grid-template-columns:1fr}}
footer{border-top:1px solid var(--line);padding:22px 20px;color:var(--mut);
font-size:12.5px;text-align:center;margin-top:40px}
footer a{color:var(--mut)}
"""


def page(title: str, body: str, *, desc: str = "", depth: int = 0) -> str:
    up = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc[:300])}">
<link rel="icon" href="{up}favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="{up}icon-192.png" sizes="192x192">
<link rel="apple-touch-icon" href="{up}icon-180.png">
<meta name="theme-color" content="#0d0f14">
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header>
  <a class="logo" href="{up}index.html">{LOGO_SVG}Drama<span>Index</span></a>
  <nav>
    <a href="{up}index.html">Trending</a>
    <a href="{up}charts.html">App Charts</a>
    <a href="{up}genres.html">Genres</a>
    <a href="{up}about.html">About</a>
  </nav>
</header>
<main>
{body}
</main>
<footer>
  <p>{SITE_NAME} indexes publicly listed short-drama metadata from official
  platform pages and public app-store charts. Not affiliated with or endorsed by
  any platform. Titles, artwork and marks belong to their respective owners.</p>
  <p><a href="{up}about.html">About &amp; data sources</a></p>
</footer>
</body>
</html>"""


def card_html(d: dict, depth: int = 0) -> str:
    up = "../" * depth
    slug = slugify(d["title"])
    pf = d.get("platform", "")
    img = d.get("cover") or ""
    img_tag = (
        f'<img src="{escape(img)}" alt="{escape(d["title"])} cover" loading="lazy">'
        if img
        else '<div style="aspect-ratio:2/3;background:#0a0c10"></div>'
    )
    return f"""<a class="card" href="{up}drama/{slug}.html">
{img_tag}
<div class="body">
<span class="t">{escape(d["title"])}</span>
<span class="pf {pf}">{escape(PLATFORM_LABELS.get(pf, pf))}</span>
</div></a>"""


def build():
    snapshots = load_snapshots()
    if not snapshots:
        print("no snapshots found; run collect.py first")
        return 1

    latest = snapshots[-1]
    dramas = merge(snapshots)
    print(f"merged {len(dramas)} dramas from {len(snapshots)} snapshot(s)")

    history = load_history()
    deltas = history_deltas(history)
    deltas_date = history[-2].get("date", "") if len(history) >= 2 else ""
    print(f"trend history: {len(history)} day(s)")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / "drama").mkdir()
    (OUT / "genre").mkdir()
    (OUT / "data").mkdir()
    (OUT / "style.css").write_text(CSS, encoding="utf-8")

    # Icons live in assets/ rather than being drawn here: build_site.py is
    # stdlib-only by design, and generating PNG/ICO would pull in Pillow. They
    # are static, so copying is enough - but it has to happen on every run,
    # because OUT is wiped first and a hand-placed file would vanish at the next
    # daily build (the same trap the CNAME file fell into).
    if ASSETS.is_dir():
        for asset in sorted(ASSETS.iterdir()):
            if asset.is_file():
                shutil.copy2(asset, OUT / asset.name)
    else:
        print(f"warning: {ASSETS} missing; site will ship without icons")

    # GitHub Pages runs Jekyll by default, which skips files it does not
    # recognise. An empty .nojekyll disables that and serves everything as-is.
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    if INDEXNOW_KEY:
        (OUT / f"{INDEXNOW_KEY}.txt").write_text(INDEXNOW_KEY, encoding="utf-8")

    if CUSTOM_DOMAIN:
        (OUT / "CNAME").write_text(CUSTOM_DOMAIN + "\n", encoding="utf-8")

    for name, content in SITE_VERIFICATION_FILES:
        name = name.strip()
        if name:
            (OUT / name).write_text(content.strip(), encoding="utf-8")

    # ---- group by platform, sorted by engagement -------------------------
    by_platform: dict[str, list[dict]] = defaultdict(list)
    for d in dramas.values():
        if d.get("title"):
            by_platform[d.get("platform", "?")].append(d)

    def engagement(d: dict) -> int:
        return int(d.get("read_count") or d.get("view_count") or 0)

    for lst in by_platform.values():
        lst.sort(key=engagement, reverse=True)

    # ---- index: cross-platform trending ----------------------------------
    all_sorted = sorted(dramas.values(), key=engagement, reverse=True)
    top = [d for d in all_sorted if d.get("title")][:24]

    rows = []
    for i, d in enumerate(all_sorted[:60], 1):
        slug = slugify(d["title"])
        pf = d.get("platform", "")
        rows.append(
            f'<tr><td class="rank">{i}</td>'
            f'<td><a href="drama/{slug}.html">{escape(d["title"])}</a></td>'
            f'<td><span class="pf {pf}">{escape(PLATFORM_LABELS.get(pf, pf))}</span></td>'
            f'<td>{fmt_num(engagement(d))}</td>'
            f'<td>{fmt_num(d.get("chapter_count"))}</td></tr>'
        )

    latest_date = latest.get("date", "")
    appstore = latest.get("appstore", [])
    free = [a for a in appstore if a["chart"] == "us_ent_free"][:8]

    body = f"""
<h1>Short drama, indexed</h1>
<p class="sub">{len(dramas):,} series tracked across
{len(by_platform)} platforms &middot; updated {escape(latest_date)}</p>

<div class="meta">
  <div><b>Series</b>{len(dramas):,}</div>
  <div><b>Platforms</b>{len(by_platform)}</div>
  <div><b>Last crawl</b>{escape(latest_date)}</div>
</div>

<h2>Trending now</h2>
<div class="grid">
{"".join(card_html(d) for d in top)}
</div>

<h2>Top 60 by lifetime reads</h2>
<table>
<thead><tr><th>#</th><th>Title</th><th>Platform</th><th>Reads</th><th>Eps</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>

<div class="note">
<b>How rankings work.</b> Ordering uses the lifetime read/view counter each
platform publishes on its own pages. Those counters are platform-specific and
not directly comparable, so treat the cross-platform table as a rough guide and
use the per-platform pages for like-for-like comparison.
</div>
"""
    (OUT / "index.html").write_text(
        page(
            f"{SITE_NAME} - Short Drama Database & Trend Tracker",
            body,
            desc="Browse and track short drama series from ReelShort and DramaBox: "
            "episode counts, genres, popularity and app-store chart movement.",
        ),
        encoding="utf-8",
    )

    # ---- genre grouping (built before the pages so pills only ever link to
    # hubs that actually exist) ---------------------------------------------
    MIN_GENRE_HUB = 3
    genre_map: dict[str, list[dict]] = defaultdict(list)
    for d in dramas.values():
        if not d.get("title"):
            continue
        tags = d.get("themes") or d.get("tags") or d.get("subgenres") or []
        if isinstance(tags, str):
            tags = [tags]
        for t in set(list(tags) + list(d.get("genres") or [])):
            if t:
                genre_map[str(t)].append(d)

    hub_slugs = {
        slugify(g)
        for g, items in genre_map.items()
        if len(items) >= MIN_GENRE_HUB
    }

    # Titles that exist on a platform with a working referral link, keyed by a
    # loose normalised title. ~3,047 of the pages are DramaBox, which has no
    # affiliate programme at all, so without this their outbound link earns
    # nothing. Where the same series is also on ReelShort we can offer the
    # earning link alongside it instead of leaving the page unmetered.
    referral_titles: dict[str, str] = {}
    for d in dramas.values():
        if d.get("platform") in REFERRAL_LINKS and d.get("title"):
            referral_titles.setdefault(norm_title(d["title"]), d["title"])

    # Slugs have to be assigned for every series before any page renders, so a
    # page can link to another series' page that has not been written yet. Doing
    # it inside the render loop previously meant recommendations could only be
    # emitted for already-written pages, which is order-dependent and wrong.
    slugs: dict[str, str] = {}
    _used: dict[str, int] = {}
    for key, d in dramas.items():
        if not d.get("title"):
            continue
        s = slugify(d["title"])
        if s in _used:
            _used[s] += 1
            s = f"{s}-{_used[s]}"
        else:
            _used[s] = 1
        slugs[key] = s

    # Only same-title matches exist between the two catalogues (88 of 3,031),
    # which would leave 97% of DramaBox pages with no earning route. So when
    # there is no title match, fall back to the best-performing ReelShort series
    # sharing a theme: the recommendation is still relevant, and it points at a
    # page whose own link earns.
    def themed_alternatives(d: dict, limit: int = 3) -> list[dict]:
        tags = {
            t
            for t in (list(d.get("themes") or d.get("tags") or []) + list(d.get("genres") or []))
            if t
        }
        if not tags:
            return []
        scored = []
        for k, cand in dramas.items():
            if cand.get("platform") not in REFERRAL_LINKS or not cand.get("title"):
                continue
            ctags = set(
                list(cand.get("themes") or cand.get("tags") or [])
                + list(cand.get("genres") or [])
            )
            overlap = len(tags & ctags)
            if overlap:
                scored.append((overlap, engagement(cand), k, cand))
        scored.sort(key=lambda r: (-r[0], -r[1]))
        return [c for _, _, _, c in scored[:limit]]

    # Peer groups for the per-page comparison. Both platforms publish a ranking
    # number, but neither publishes what it means relative to the rest of its
    # category - and that comparison is the single most useful thing a reader
    # can be told, because it is what distinguishes a hidden gem from a
    # front-page hit. Computed once for the whole catalogue rather than per page
    # (4,391 pages x a full scan would be quadratic).
    peer_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in dramas.values():
        pf = d.get("platform")
        if not d.get("title"):
            continue
        grp = d.get("shelf") if pf == "reelshort" else d.get("category")
        if grp:
            peer_groups[(pf, str(grp))].append(d)

    def peer_stats(d: dict) -> dict | None:
        """Where this series sits among its category peers."""
        pf = d.get("platform")
        grp = d.get("shelf") if pf == "reelshort" else d.get("category")
        if not grp or str(grp) in SKIP_GROUPS:
            return None
        peers = peer_groups.get((pf, str(grp))) or []
        if len(peers) < 5:
            return None
        label = (
            SHELF_LABELS.get(str(grp), str(grp))
            if pf == "reelshort"
            else str(grp)
        )

        def metric(x: dict):
            return x.get("read_count") or x.get("follow_count") or 0

        ranked = sorted(peers, key=metric, reverse=True)
        mine = metric(d)
        if not mine:
            return None
        better = sum(1 for x in ranked if metric(x) > mine)
        pct = 1 - (better / len(ranked))
        return {
            "group": label,
            "n": len(ranked),
            "rank": better + 1,
            "top_pct": pct,
            "median": ranked[len(ranked) // 2].get("title", ""),
        }

    # ---- per-drama pages --------------------------------------------------
    written = 0
    for key, d in dramas.items():
        if not d.get("title"):
            continue
        slug = slugs[key]

        pf = d.get("platform", "")
        themes = d.get("themes") or d.get("tags") or d.get("subgenres") or []
        if isinstance(themes, str):
            themes = [themes]
        genres = d.get("genres") or []
        raw_desc = d.get("description") or ""
        desc = excerpt(raw_desc)
        plat_label = PLATFORM_LABELS.get(pf, pf)

        # Only report a metric when the platform actually publishes it.
        # DramaBox exposes follows and a rating but not view counts, so a shared
        # "Reads" row rendered as "-" on 3,294 of its pages - a blank field that
        # makes the page look broken and tells a reader nothing. Each platform
        # now shows what it really has.
        stats = [
            ("Platform", plat_label),
            ("Episodes", fmt_num(d.get("chapter_count"))),
        ]
        if pf == "reelshort":
            stats.append(("Reads", fmt_num(d.get("read_count"))))
            if d.get("collect_count"):
                stats.append(("Collects", fmt_num(d["collect_count"])))
        else:
            if d.get("follow_count"):
                stats.append(("Followers", fmt_num(d["follow_count"])))
            if d.get("rating"):
                stats.append(("Rating", f"{d['rating']}/10"))
            if d.get("view_count"):
                stats.append(("Views", fmt_num(d["view_count"])))
        if d.get("lang"):
            stats.append(("Language", str(d["lang"]).upper()))
        if d.get("paid_start_chapter"):
            stats.append(("Free episodes", str(d["paid_start_chapter"])))
        if d.get("author"):
            stats.append(("Author", d.get("author")))

        # Facts a reader can use but that neither platform states outright. This
        # is the part of the page that is ours: the underlying numbers are
        # public, but the comparisons drawn from them are not, and a page of
        # them is materially more useful than a synopsis plus a link. It is also
        # the honest answer to "why index this rather than just use the app" -
        # the platform never tells you the paywall ratio or the completion rate.
        facts = []
        n_ch = d.get("chapter_count")
        ps = d.get("paid_start_chapter")
        if isinstance(n_ch, int) and n_ch > 0:
            if isinstance(ps, int) and ps > 1:
                free = ps - 1
                pct = free / n_ch
                verdict = (
                    "a generous free run"
                    if pct >= 0.25
                    else "a short free run"
                    if pct <= 0.10
                    else "a typical free run"
                )
                facts.append(
                    f"<b>{free} of {n_ch} episodes</b> are free before the "
                    f"paywall &mdash; {verdict} ({pct:.0%} of the series)."
                )
            elif isinstance(ps, int):
                facts.append("<b>Paid from the first episode.</b>")
            facts.append(
                f"At 1&ndash;2 minutes an episode, the full {n_ch} runs about "
                f"<b>{n_ch * 1.2 / 60:.0f}&ndash;{n_ch * 2.0 / 60:.0f} hours</b>."
            )
        rc, cc = d.get("read_count"), d.get("collect_count")
        if rc and cc:
            rate = cc / rc
            facts.append(
                f"<b>{rate:.1%}</b> of readers collect it &mdash; roughly 1 in "
                f"{max(1, round(1 / rate)):,} decide to keep it."
            )
        if d.get("has_trailer"):
            facts.append("A trailer is available on the platform page.")

        # The comparison that neither platform offers: how this series sits
        # against its own category. "Top 8% of 236 CEO dramas" is a judgement a
        # reader cannot make themselves without opening all 236.
        ps_stats = peer_stats(d)
        if ps_stats:
            pct = ps_stats["top_pct"]
            # Neutral phrasing below the top quarter. These pages exist to send
            # a reader onward, and "the quieter half" reads as a warning - it
            # would talk them out of the very series they came to look at. The
            # rank itself already carries the information for anyone who wants
            # it, so the label only needs to place it, not judge it.
            where = (
                "the top 5% of the category"
                if pct >= 0.95
                else "the top 10% of the category"
                if pct >= 0.90
                else "the top quarter of the category"
                if pct >= 0.75
                else "the more-watched half"
                if pct >= 0.50
                else "a mid-catalogue title"
            )
            facts.append(
                f"Ranks <b>#{ps_stats['rank']} of {ps_stats['n']}</b> in "
                f"{escape(ps_stats['group'])} &mdash; {where}."
            )

        facts_html = ""
        if facts:
            facts_html = (
                '<h2 style="font-size:16px;margin:20px 0 6px">'
                "What the numbers say</h2>"
                '<ul style="margin:0;padding-left:20px">'
                + "".join(f"<li>{f}</li>" for f in facts)
                + "</ul>"
            )

        # Day-over-day movement for this series, when two days exist. Shown as
        # an explicit arrow rather than a bare number so the direction reads
        # without comparing against anything.
        ch = (deltas.get(pf) or {}).get(d.get("platform_id") or "")
        if ch and not ch.get("new"):
            rk = ch.get("shelf_rank") or ch.get("rank")
            if isinstance(rk, dict) and rk.get("delta"):
                arrow = "\u25b2" if rk["delta"] < 0 else "\u25bc"
                stats.append(
                    (
                        "Rank change",
                        f'{arrow} {int(rk["prev"])} \u2192 {int(rk["cur"])}',
                    )
                )
            rd = ch.get("read_count") or ch.get("view_count")
            if isinstance(rd, dict) and rd.get("delta"):
                sign = "+" if rd["delta"] > 0 else "\u2212"
                stats.append(("Reads change", f"{sign}{fmt_num(abs(rd['delta']))}"))

        meta_html = "".join(
            f"<div><b>{escape(str(k))}</b>{escape(str(v))}</div>" for k, v in stats
        )

        # Link a tag only if its hub was actually generated; otherwise render a
        # plain pill so we never emit a link to a page that does not exist.
        pill_parts = []
        for t in (list(genres) + list(themes))[:12]:
            gs = slugify(str(t))
            if gs in hub_slugs:
                pill_parts.append(
                    f'<a class="pill" href="../genre/{gs}.html">{escape(str(t))}</a>'
                )
            else:
                pill_parts.append(f'<span class="pill">{escape(str(t))}</span>')
        pills = "".join(pill_parts)

        # JSON-LD: give search engines and AI crawlers a clean entity.
        ld = {
            "@context": "https://schema.org",
            "@type": "TVSeries",
            "name": d["title"],
            "numberOfEpisodes": d.get("chapter_count"),
            "inLanguage": d.get("lang"),
            "description": desc,
        }
        if d.get("cover"):
            ld["image"] = d["cover"]
        if genres:
            ld["genre"] = genres

        # Cross-platform prompt: only when this page's own platform has no
        # referral route. Prefer the same series on ReelShort; otherwise
        # recommend thematically similar series whose pages carry the link.
        # These point at our own pages, so the reader lands somewhere useful
        # and the referral fires on the next click rather than being pushed at
        # them immediately.
        cross_html = ""
        if pf not in REFERRAL_LINKS:
            alt_title = referral_titles.get(norm_title(d["title"]))
            if alt_title:
                cross_html = f"""
    <p style="margin-top:14px">
      <a href="{escape(outbound_url('reelshort'))}" rel="nofollow sponsored noopener"
         target="_blank">Also on ReelShort &mdash; open the app and search &ldquo;{escape(alt_title)}&rdquo; &rarr;</a>
    </p>
    {affiliate_note('reelshort')}"""
            else:
                alts = themed_alternatives(d)
                if alts:
                    items = "".join(
                        f'<li><a href="{escape(slugs[k])}.html">{escape(a["title"])}</a></li>'
                        for a in alts
                        if (k := f"{a.get('platform')}:{a.get('platform_id')}") in slugs
                    )
                    if items:
                        cross_html = f"""
    <div class="note" style="margin-top:14px">
      More on ReelShort (we earn a commission on those links):
      <ul style="margin:6px 0 0 18px;padding:0">{items}</ul>
    </div>"""

        detail = f"""
<h1>{escape(d["title"])}</h1>
<div class="detail">
  <div>
    {f'<img src="{escape(d["cover"])}" alt="{escape(d["title"])} cover">' if d.get("cover") else ""}
    <p style="margin-top:14px">
      <a href="{escape(outbound_url(pf))}" rel="nofollow sponsored noopener"
         target="_blank">{watch_label(pf, d["title"])} &rarr;</a>
    </p>
    {affiliate_note(pf)}{cross_html}
  </div>
  <div>
    <div class="meta">{meta_html}</div>
    {facts_html}
    {f'<p style="margin-top:14px">{escape(desc)}</p>' if desc else ''}
    {f'<div style="margin-top:14px">{pills}</div>' if pills else ''}
    <div class="note">
      Synopsis quoted in brief from {escape(plat_label)}; see the
      <a href="{escape(outbound_url(pf))}" rel="nofollow noopener"
         target="_blank">full listing on {escape(plat_label)}</a>.
      Data last verified {escape(d.get("last_seen",""))}. Episode counts and
      availability change often &mdash; confirm on the platform before relying on it.
    </div>
  </div>
</div>
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
"""
        (OUT / "drama" / f"{slug}.html").write_text(
            page(
                f"{d['title']} - {plat_label} | {SITE_NAME}",
                detail,
                desc=f"{d['title']} on {plat_label}. {desc}",
                depth=1,
            ),
            encoding="utf-8",
        )
        written += 1

    # ---- genre hubs -------------------------------------------------------
    genre_rows = []
    for g, items in sorted(genre_map.items(), key=lambda kv: -len(kv[1])):
        if len(items) < MIN_GENRE_HUB:
            continue
        gs = slugify(g)
        items.sort(key=engagement, reverse=True)
        gbody = f"""
<h1>{escape(g)} short dramas</h1>
<p class="sub">{len(items)} series tagged {escape(g)}</p>
<div class="grid">{"".join(card_html(d, depth=1) for d in items[:60])}</div>
"""
        (OUT / "genre" / f"{gs}.html").write_text(
            page(
                f"{g} Short Dramas ({len(items)}) | {SITE_NAME}",
                gbody,
                desc=f"{len(items)} short drama series tagged {g} across ReelShort and DramaBox.",
                depth=1,
            ),
            encoding="utf-8",
        )
        genre_rows.append(
            f'<li><a href="genre/{gs}.html">{escape(g)}</a> '
            f'<span style="color:var(--mut)">{len(items)}</span></li>'
        )

    (OUT / "genres.html").write_text(
        page(
            f"Short Drama Genres | {SITE_NAME}",
            f"<h1>Genres</h1><p class='sub'>{len(genre_rows)} tags</p>"
            f"<ul style='columns:2;list-style:none;padding:0'>{''.join(genre_rows)}</ul>",
            desc="Browse short drama series by genre and theme tag.",
        ),
        encoding="utf-8",
    )

    # ---- charts -----------------------------------------------------------
    gross = [a for a in appstore if a["chart"] == "us_ent_grossing"]
    free_all = [a for a in appstore if a["chart"] == "us_ent_free"]

    def chart_table(items, title):
        rows = "".join(
            f'<tr><td class="rank">{a["rank"]}</td><td>{escape(a["name"])}</td>'
            f'<td style="color:var(--mut)">{escape(a["developer"])}</td></tr>'
            for a in sorted(items, key=lambda x: x["rank"])
        )
        return (
            f"<h2>{title}</h2><table><thead><tr><th>#</th><th>App</th>"
            f"<th>Developer</th></tr></thead><tbody>{rows}</tbody></table>"
        )

    # Movement, from the committed trend series. This is the part no competitor
    # can copy: a platform only ever shows today's numbers, so yesterday's rank
    # is gone unless someone recorded it. Rendered only once there are two days
    # to compare - with one day there is no movement, and inventing one would be
    # worse than showing nothing.
    movers_html = ""
    if deltas:
        titles = {k: v.get("title", "") for k, v in dramas.items()}
        slugs_by_key = {k: slugs.get(k, "") for k in dramas}
        up, down = [], []
        for pf, rows in deltas.items():
            for pid, ch in rows.items():
                key = f"{pf}:{pid}"
                rk = ch.get("shelf_rank") or ch.get("rank")
                if not isinstance(rk, dict) or not rk.get("delta"):
                    continue
                delta = rk["delta"]  # negative = moved up the chart
                title = titles.get(key) or pid
                slug = slugs_by_key.get(key)
                label = (
                    f'<a href="drama/{escape(slug)}.html">{escape(title)}</a>'
                    if slug
                    else escape(title)
                )
                row = (
                    f"<li>{label} "
                    f'<span style="color:var(--mut)">#{int(rk["prev"])} &rarr; '
                    f'#{int(rk["cur"])}</span></li>'
                )
                (up if delta < 0 else down).append((abs(delta), row))
        up.sort(key=lambda t: -t[0])
        down.sort(key=lambda t: -t[0])
        if up or down:
            movers_html = (
                "<h2>Biggest movers</h2>"
                f"<p class='sub'>Change since {escape(deltas_date)}</p>"
                "<div class='detail'><div><h3>Rising</h3><ul>"
                + ("".join(r for _, r in up[:15]) or "<li>-</li>")
                + "</ul></div><div><h3>Falling</h3><ul>"
                + ("".join(r for _, r in down[:15]) or "<li>-</li>")
                + "</ul></div></div>"
            )

    (OUT / "charts.html").write_text(
        page(
            f"Short Drama App Store Rankings | {SITE_NAME}",
            f"<h1>App Store charts</h1>"
            f"<p class='sub'>US Entertainment category &middot; {escape(latest_date)}</p>"
            + movers_html
            + chart_table(gross, "Top grossing")
            + chart_table(free_all, "Top free")
            + "<div class='note'>Rankings come from Apple's public RSS chart "
            "feed for the US Entertainment category, filtered to short-drama "
            "apps. Snapshots accumulate daily so movement can be tracked.</div>",
            desc="Daily US App Store rankings for short drama apps, plus the biggest daily movers.",
        ),
        encoding="utf-8",
    )

    # ---- about ------------------------------------------------------------
    (OUT / "about.html").write_text(
        page(
            f"About | {SITE_NAME}",
            f"""<h1>About {SITE_NAME}</h1>
<p>{SITE_NAME} is an independent index of short-form drama series. It collects
metadata that platforms publish publicly on their own pages and app-store
charts, and presents it in one place so the catalogue can be browsed and
compared.</p>

<h2>What we collect</h2>
<ul>
<li>Series title, synopsis, episode count, cover artwork</li>
<li>Public engagement counters (reads, collects, views) as published</li>
<li>Genre and theme tags</li>
<li>Public app-store chart positions</li>
</ul>

<h2>What we do not collect</h2>
<ul>
<li>No video, no episode bodies, no paywalled content</li>
<li>No logged-in or partner-only data</li>
<li>No personal data</li>
<li>No full reproduction of platform synopses &mdash; we quote a short
excerpt for identification and link to the source listing</li>
</ul>

<h2>Sources</h2>
<ul>
<li>ReelShort public shelf pages</li>
<li>DramaBox public browse pages</li>
<li>Apple App Store public RSS chart feeds</li>
</ul>

<h2>Freshness</h2>
<p>Data is re-crawled periodically. Series pages show the last verification
date. Short-drama catalogues change quickly &mdash; always confirm details on the
platform itself before making decisions.</p>

<h2>Independence</h2>
<p>This site is not affiliated with, endorsed by, or operated by any short-drama
platform. All titles, artwork, and trademarks belong to their respective owners.
Where outbound links are present they may be referral links.</p>""",
            desc=f"About {SITE_NAME}: data sources, collection policy, and independence.",
        ),
        encoding="utf-8",
    )

    # ---- machine-readable feeds ------------------------------------------
    feed = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(dramas),
        "dramas": [
            {
                "title": d.get("title"),
                "platform": d.get("platform"),
                "episodes": d.get("chapter_count"),
                "reads": d.get("read_count") or d.get("view_count"),
                "genres": d.get("genres") or d.get("themes") or [],
                "url": f"drama/{slugify(d['title'])}.html",
            }
            for d in all_sorted
            if d.get("title")
        ],
    }
    (OUT / "data" / "dramas.json").write_text(
        json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (OUT / "data" / "appstore.json").write_text(
        json.dumps(appstore, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # ---- sitemap / robots -------------------------------------------------
    urls = ["index.html", "charts.html", "genres.html", "about.html"]
    urls += [f"drama/{s}.html" for s in sorted(slugs.values())]
    urls += [
        f"genre/{slugify(g)}.html"
        for g, items in genre_map.items()
        if len(items) >= MIN_GENRE_HUB
    ]
    # lastmod must be UTC. Using local time on a UTC+8 machine stamps dates a
    # day ahead of the crawler's clock, and a future lastmod is a documented
    # reason for a sitemap to be rejected outright.
    today = datetime.now(timezone.utc).date().isoformat()
    sm = "\n".join(
        f"  <url><loc>{SITE_SCHEME}://{SITE_DOMAIN}/{u}</loc>"
        f"<lastmod>{today}</lastmod></url>"
        for u in urls
    )
    (OUT / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{sm}\n</urlset>\n',
        encoding="utf-8",
    )
    (OUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\n"
        "User-agent: GPTBot\nAllow: /\n\n"
        "User-agent: OAI-SearchBot\nAllow: /\n\n"
        "User-agent: ClaudeBot\nAllow: /\n\n"
        "User-agent: PerplexityBot\nAllow: /\n\n"
        "User-agent: Google-Extended\nAllow: /\n\n"
        f"Sitemap: {SITE_SCHEME}://{SITE_DOMAIN}/sitemap.xml\n",
        encoding="utf-8",
    )

    print(
        f"built site -> {OUT}\n"
        f"  drama pages: {written}\n"
        f"  genre hubs:  {sum(1 for g,i in genre_map.items() if len(i)>=3)}\n"
        f"  urls:        {len(urls)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
