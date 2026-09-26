# Market Monitor — build notes (for the daily auto-refresh)

## Layout
- `scripts/fetch_quotes.py` → `data/quotes.json`  (indices + watchlist)
- `scripts/fetch_pelosi.py` → `data/pelosi.json`  (House PTR transactions)
- `scripts/fetch_trump.py`  → `data/trump.json`   (OGE 278e holdings)
- `scripts/build.py`        → `app/index.html`    (self-contained page, inline CSS)
- `app/server.js`           → static server on $PORT (for `publish`)
- `run_all.sh`              → all of the above in order

## Source findings (2026-08-09)
- **Stooq is dead as an automated source**: `stooq.com/q/d/l/` now returns a JavaScript
  proof-of-work anti-bot page instead of CSV. Kept as fallback; it raises cleanly.
- **Yahoo Finance chart API works, but fingerprints the client.** Python `urllib` gets an
  instant HTTP 429 no matter the headers; so does `curl --compressed` with a full Chrome UA.
  `curl -A "Mozilla/5.0"` (no --compressed) returns 200. Hence all HTTP goes through curl.
  Add ~0.7 s between symbols and retry with backoff across query1/query2.
- **Daily % change**: must use the second-to-last *daily bar*, NOT `meta.chartPreviousClose`
  — with `range=1mo` that field is the close before the whole window (it produced fake
  -22% moves on the first pass).
- **House Stock Watcher S3 bucket is 403 (Access Denied)** — the dataset the brief named is
  offline. Fallback in use: official Clerk of the House data —
  `financial-pdfs/<year>FD.zip` (XML index, FilingType `P` = Periodic Transaction Report)
  then `ptr-pdfs/<year>/<DocID>.pdf`, text-extracted with `pypdf`. The fetcher still tries
  House Stock Watcher first and will use it automatically if the bucket comes back.
- **Trump 278e**: `extapps2.oge.gov/201/Presiden.nsf/PAS+Index/69AEAA9D7455ACD585258E27002DDEE1/$FILE/Donald-J-Trump-2026-278ANNUAL.pdf`
  (927 pages, annual report year 2025, OGE received 2026-06-29). Parser reads Part 6 asset
  lines. **This URL is hash-based and will change with the next annual filing** — for the
  daily job, re-discover it rather than hard-coding forever. Only worth re-fetching weekly;
  it changes once a year.

## Publishing
`publish` currently fails on this machine: `spawn docker ENOENT` — no container runtime, so
the deployment starts and immediately stops. Deployment record `market-monitor`
(id 336a5df5-6139-4020-89a5-98c7cab19566) exists at version 2 but has no reachable URL.
Retry `publish` once the deployment runtime is enabled; the app dir is ready as-is.

## Daily refresh (added 2026-08-09)
- `run_all.sh` → `scripts/refresh.py` is the entry point for the cron.
- Each source runs in a scratch dir and is promoted to `data/` only if its JSON validates
  (quotes: indices+watchlist non-empty; pelosi: ok+rows; trump: ok+holdings). A failed
  source therefore keeps its **last good** file rather than being overwritten.
- The page is built to `app/index.html.new` and swapped in only on success, so
  `app/index.html` is never left broken.
- `RUN_STATUS` env carries per-source results into `build.py`, which renders an amber
  "Stale — showing the last good … data" bar over any section that did not refresh
  (also triggered by data older than 30 h) plus a refresh line in the footer.
- Per-run state: `data/run_status.json`, appended history in `logs/runs.log`.
- The 278e PDF is cached at `data/cache/trump278.pdf` and re-downloaded only weekly —
  it is an annual filing, so daily downloads of 8 MB are pointless.
- Full cycle measured at ~55 s with a warm PDF cache.
- Still no container runtime here, so `publish` keeps failing with `spawn docker ENOENT`
  and the deployment's git remote 404s (it never built). The cron retries `publish` on
  every run; the name `market-monitor` is reserved so the URL will be stable once it works.

## Signal-over-noise upgrade (2026-08-09)
- `build.py` was rewritten around a "Today" hero strip (top movers, 52w extremes and
  near-extremes, risk-regime read, new Pelosi filings — capped at 8 bullets, and it says
  "quiet session" rather than padding when nothing moved >0.75%).
- Quotes now pull `range=3mo` so one call yields day/5d/1M changes plus a 30-bar
  sparkline. Sparklines are inline `<svg>` polylines built in `build.py` — no chart
  library, no external asset, no runtime fetch. Verified: the page has zero external
  `src`/`href` references.
- New per-symbol fields: `month_pct`, `spark`, `range_pos`, `from_high_pct`,
  `from_low_pct`, `new_52w_high`, `new_52w_low` (new extremes are detected by comparing
  the session's day high/low against the 52-week high/low from Yahoo's `meta`).
- **^TNX quirk:** this endpoint currently returns the 10-year yield already in percent
  (4.66), NOT the historical yield x10 (46.6). The fetcher normalises defensively
  (divides by 10 only if the value exceeds 25), and the page shows the daily move in
  **basis points** — a percentage change of a yield is meaningless to read.
- Macro row: ^VIX, ^TNX, EURUSD=X, BTC-USD via the same curl+backoff path. BTC quotes
  around the clock, so its "day change" moves even when equity markets are shut.
- New-vs-old Pelosi split: `refresh.py` keeps `data/pelosi_seen.json` (transaction keys
  promoted only after a successful build) and writes `new_keys` into pelosi.json;
  the first ever run seeds the file so it can't cry "NEW" about the whole history.
  Older filings are collapsed into a `<details>` fold, as is the whole Trump section.
- Watchlist is sorted by absolute day move; rows under ±0.5% are dimmed, rows at ±3% or a
  new 52-week extreme get a highlighted background and a left rule. Emphasis and opacity
  only — no extra colours beyond the existing green/red, which keep their arrows and signs.

## Audit fixes (2026-09-26)
- **Pelosi parser was silently dropping filings.** The PTR regex required the two dates glued
  together (`01/16/202601/16/2026`); current PDFs/pypdf put a space between them, so the
  8/21/2026 PTR (BE, INTC, REOF XXV — trades of 24–28 Jul) never appeared while the page
  said "no new filings". Fix: `\s*` between the dates, ticker made optional (LLCs/funds),
  cap raised from 10 to 40 rows. Each PTR listed in the Clerk index must now yield ≥1 row,
  otherwise the fetcher exits non-zero → the section goes **stale** instead of lying.
- **Trump: 278-T transaction reports were not tracked at all** — only the annual 278e.
  `fetch_trump.py` now discovers every Trump filing through OGE's index API
  (`extapps2.oge.gov/201/Presiden.nsf/API.xsp/v2/rest`), so the annual URL is no longer
  hard-coded, and parses the 278-Ts of the last 12 months (OCR-tolerant: `lourchaso`,
  `717/2026`, amounts snapped to OGE brackets). Coverage (lines read vs line numbers seen)
  is shown; if < 50% and tesseract is installed, the PDF is re-OCR'd. The 08/12/2026 278-T is
  image-only: it needs tesseract (installed in the GitHub Action, not on this Mac —
  Homebrew has no bottle for macOS 14).
- New-report detection for 278-Ts: `data/trump_seen.json` (same scheme as `pelosi_seen.json`).
- `refresh.py`: cache promotion now copies sub-directories (`data/cache/278t/`).

## GitHub (2026-09-26)
- Source lives on branch `main` of `franzrub/market-monitor`; the page is served by Pages
  from `gh-pages`. Workflow `.github/workflows/refresh.yml`: Mon/Wed/Fri 20:30 UTC + manual.
  It commits `data/*.json` and `app/index.html` back to `main`, and publishes to `gh-pages`
  **only** when the repo variable `DEPLOY_PAGES=true` (or "deploy" ticked on a manual run).
- Scheduled workflows run only from the default branch (currently `gh-pages`).
- Locally: `pypdf` is not in the system python; use a venv (`pip install -r requirements.txt`).
