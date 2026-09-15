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
OUT = ROOT / "site"

SITE_NAME = "DramaIndex"
SITE_TAGLINE = "The short-drama database"

# Set SITE_DOMAIN (or env DRAMADB_DOMAIN) once a domain is live so sitemap and
# robots.txt emit absolute URLs. Until then we emit a clearly-marked placeholder
# rather than silently shipping a wrong canonical host.
SITE_DOMAIN = os.environ.get("DRAMADB_DOMAIN", "example.com").rstrip("/")
SITE_SCHEME = "https"

# IndexNow key: hosting <key>.txt at the site root proves domain ownership so
# search engines accept bulk URL submissions without an account. Generated
# once and kept stable; changing it invalidates prior submissions.
INDEXNOW_KEY = os.environ.get("DRAMADB_INDEXNOW_KEY", "").strip()

# Referral/affiliate base URLs. Left blank until the affiliate account exists;
# blank means outbound links are plain (non-monetised) links, which keeps the
# site honest while the affiliate application is pending.
REFERRAL_LINKS: dict[str, str] = {
    # "reelshort": "https://...?ref=XXXX",
    # "dramabox": "https://...?ref=XXXX",
}

PLATFORM_LABELS = {
    "reelshort": "ReelShort",
    "dramabox": "DramaBox",
}

PLATFORM_URLS = {
    "reelshort": "https://www.reelshort.com/",
    "dramabox": "https://www.dramabox.com/",
}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:80] or "untitled"


def load_snapshots() -> list[dict]:
    snaps = []
    for f in sorted(SNAP_DIR.glob("*.json")):
        try:
            snaps.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return snaps


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
.logo{font-weight:700;font-size:18px;color:var(--tx)}
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
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header>
  <a class="logo" href="{up}index.html">Drama<span>Index</span></a>
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

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / "drama").mkdir()
    (OUT / "genre").mkdir()
    (OUT / "data").mkdir()
    (OUT / "style.css").write_text(CSS, encoding="utf-8")

    # GitHub Pages runs Jekyll by default, which skips files it does not
    # recognise. An empty .nojekyll disables that and serves everything as-is.
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    if INDEXNOW_KEY:
        (OUT / f"{INDEXNOW_KEY}.txt").write_text(INDEXNOW_KEY, encoding="utf-8")

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

    # ---- per-drama pages --------------------------------------------------
    used_slugs: dict[str, int] = {}
    written = 0
    for key, d in dramas.items():
        if not d.get("title"):
            continue
        slug = slugify(d["title"])
        if slug in used_slugs:
            used_slugs[slug] += 1
            slug = f"{slug}-{used_slugs[slug]}"
        else:
            used_slugs[slug] = 1

        pf = d.get("platform", "")
        themes = d.get("themes") or d.get("tags") or d.get("subgenres") or []
        if isinstance(themes, str):
            themes = [themes]
        genres = d.get("genres") or []
        raw_desc = d.get("description") or ""
        desc = excerpt(raw_desc)
        plat_label = PLATFORM_LABELS.get(pf, pf)

        stats = [
            ("Platform", plat_label),
            ("Episodes", fmt_num(d.get("chapter_count"))),
            ("Reads", fmt_num(d.get("read_count") or d.get("view_count"))),
        ]
        if d.get("collect_count"):
            stats.append(("Collects", fmt_num(d["collect_count"])))
        if d.get("lang"):
            stats.append(("Language", str(d["lang"]).upper()))
        if d.get("paid_start_chapter"):
            stats.append(("Free episodes", str(d["paid_start_chapter"])))
        if d.get("author"):
            stats.append(("Author", d["author"]))

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

        detail = f"""
<h1>{escape(d["title"])}</h1>
<div class="detail">
  <div>
    {f'<img src="{escape(d["cover"])}" alt="{escape(d["title"])} cover">' if d.get("cover") else ""}
    <p style="margin-top:14px">
      <a href="{escape(outbound_url(pf))}" rel="nofollow sponsored noopener"
         target="_blank">Watch on {escape(plat_label)} &rarr;</a>
    </p>
    {affiliate_note(pf)}
  </div>
  <div>
    <div class="meta">{meta_html}</div>
    {f'<p>{escape(desc)}</p>' if desc else ''}
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

    (OUT / "charts.html").write_text(
        page(
            f"Short Drama App Store Rankings | {SITE_NAME}",
            f"<h1>App Store charts</h1>"
            f"<p class='sub'>US Entertainment category &middot; {escape(latest_date)}</p>"
            + chart_table(gross, "Top grossing")
            + chart_table(free_all, "Top free")
            + "<div class='note'>Rankings come from Apple's public RSS chart "
            "feed for the US Entertainment category, filtered to short-drama "
            "apps. Snapshots accumulate daily so movement can be tracked.</div>",
            desc="Daily US App Store rankings for short drama apps.",
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
    urls += [f"drama/{s}.html" for s in sorted(used_slugs)]
    urls += [
        f"genre/{slugify(g)}.html"
        for g, items in genre_map.items()
        if len(items) >= MIN_GENRE_HUB
    ]
    today = date.today().isoformat()
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
