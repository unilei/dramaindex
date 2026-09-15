# DramaIndex — short-drama database & trend tracker

**Live: https://unilei.github.io/dramaindex/** (GitHub Pages, free hosting)

A static, crawlable index of short-drama series (ReelShort, DramaBox) plus
daily US App Store chart positions for the whole short-drama app category.

## What's here

```
pipeline/collect.py         crawl public catalogs -> data/snapshots/<date>.json
pipeline/build_site.py      snapshots -> site/ (HTML, sitemap, JSON feeds)
pipeline/submit_indexnow.py submit sitemap URLs to search engines
deploy.sh                   publish site/ to the gh-pages branch
run_daily.sh                crawl + build + deploy + submit, for the scheduler
data/snapshots/             one JSON per crawl day (this is the trend history)
data/raw/<date>/            raw HTTP bodies, gzipped (audit trail + rerun cache)
site/                       generated output (gitignored; lives on gh-pages)
```

## Running it

```sh
python3 pipeline/collect.py      # ~8 min, polite 1.5s delay between requests
python3 pipeline/build_site.py   # a few seconds
# or the whole chain:
DRAMADB_DOMAIN=unilei.github.io/dramaindex ./run_daily.sh
```

No third-party dependencies — standard library only.

## Scheduled job

Installed as a launchd agent so it runs daily without a terminal open:

```sh
launchctl list | grep dramadb                    # check it is registered
launchctl start com.lei.dramadb.daily            # run now
tail -f data/cron.log                            # watch it work
```

Plist: `~/Library/LaunchAgents/com.lei.dramadb.daily.plist` (09:20 daily).
launchd is used instead of cron because it runs a missed job on the next wake
rather than skipping the day — a skipped day is trend history that cannot be
recovered retroactively.

## Deploying

```sh
DRAMADB_DOMAIN=unilei.github.io/dramaindex ./deploy.sh
```

`deploy.sh` **refuses to publish** while `sitemap.xml` still contains the
`example.com` placeholder, because shipping it would teach search engines the
wrong host. Set `DRAMADB_DOMAIN` to the real host first.

Moving to a custom domain later: point the domain at GitHub Pages, then rerun
`deploy.sh` with the new `DRAMADB_DOMAIN` so sitemap, robots.txt and the
IndexNow key location all follow.

## Search submission

`submit_indexnow.py` pushes the URL set to IndexNow (Bing, Yandex, Seznam,
Naver) after each build. Ownership is proven by the `<key>.txt` file the
generator writes to the site root. Google is not on IndexNow — submit
`sitemap.xml` once in Google Search Console to cover it.

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
- No full reproduction of platform synopses. Series pages quote a short
  excerpt (≤200 chars, cut on a word boundary) for identification and link to
  the source listing. Republishing thousands of complete descriptions would be
  redistribution, not indexing.
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
