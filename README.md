# DramaIndex — short-drama database & trend tracker

A static, crawlable index of short-drama series (ReelShort, DramaBox) plus
daily US App Store chart positions for the whole short-drama app category.

## What's here

```
pipeline/collect.py     crawl public catalogs -> data/snapshots/<date>.json
pipeline/build_site.py  snapshots -> site/ (HTML, sitemap, JSON feeds)
run_daily.sh            crawl + rebuild, for cron
data/snapshots/         one JSON per crawl day (this is the trend history)
data/raw/<date>/        raw HTTP bodies, gzipped (audit trail + rerun cache)
site/                   generated output, deploy this directory
```

## Running it

```sh
python3 pipeline/collect.py      # ~8 min, polite 1.5s delay between requests
python3 pipeline/build_site.py   # a few seconds
# or both:
./run_daily.sh
```

No third-party dependencies — standard library only.

## Deploying

```sh
DRAMADB_DOMAIN=dramaindex.com python3 pipeline/build_site.py
# then upload site/ to any static host (Cloudflare Pages, Netlify, S3, nginx)
```

Set `DRAMADB_DOMAIN` **before** the final build so `sitemap.xml` and
`robots.txt` carry real absolute URLs. Without it they emit `example.com`,
which is a placeholder and must not be shipped.

## Data sources and their terms

| Source | What we take | Terms |
|---|---|---|
| ReelShort shelf pages | title, synopsis, cover, episode count, reads, collects, themes | `robots.txt` = `Allow: /` for all agents |
| DramaBox browse pages | title, synopsis, cover, episode count, views, genres | `robots.txt` allows browsing; we stay out of the disallowed `/uc`, `/renewal`, `/search` paths |
| Apple App Store RSS | public chart rank, app name, developer | Public RSS feed, no key required |

Netshort is **not** crawled: its `robots.txt` names GPTBot, ClaudeBot, CCBot,
Bytespider, Amazonbot and Google-Extended specifically. That is an explicit
opt-out and it is respected.

### What we deliberately do not collect

- No video, no episode bodies, no paywalled chapters.
- No logged-in or partner-only endpoints. The RS Boost distributor portal
  (`cps.reelshort.com`) is behind a login and is never touched by this
  pipeline — its terms forbid scraping its data for commercial use.
- No personal data.

## Monetisation

The site ships with an affiliate hook that is **off by default**:

```python
REFERRAL_LINKS = {"reelshort": "https://...?ref=XXXX"}
```

While it is empty, outbound links are plain links and no disclosure is shown.
The moment a key is added, that platform's links become `rel="nofollow
sponsored"` and a visible "referral link" disclosure appears next to them.
This is deliberate: no undisclosed paid links, ever.

## Freshness

The app-store chart positions and shelf ranks are only meaningful as a time
series. `data/snapshots/` accumulates one file per day; that history is the
part competitors are not publishing, because it cannot be bought retroactively.
