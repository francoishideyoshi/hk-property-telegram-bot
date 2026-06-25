# CODER — Changes

Implemented per `.pipeline/spec.md` §3 proposals as constrained by §6 OWNER RESOLUTIONS (§6 wins on conflict).

## Files changed / created

### `scraper.py` (modified)
- **Three distinct Telegram messages** (goal #2, spec §3c, resolution #5): Replaced the
  "join 3 sections into one `full_msg` + char-chunk" block in `run()` with a loop that sends
  THREE independent `tg_send` messages in order — RENTAL — ME, RENTAL — CLIENT, BUY / TRANSACTIONS.
  Each message is self-contained: the date header (`📊 HK Property Daily Report — <date>`) is
  prepended to every message. Reuses existing builders `build_message_rental_me/_client/_buy`
  unchanged. Empty categories send a short per-category "No new listings…" message that includes
  the category's emoji header, so all three always arrive. The existing 4000-char chunking is kept
  but applied PER category message. The separate `build_error_message` send remains as a 4th send;
  the inter-send `time.sleep(1)` is preserved.
- **ScraperAPI error clarity** (resolution #1, spec §3b): In `fetch_via_scraperapi`, HTTP 403/429
  are now detected specifically and logged as "ScraperAPI credits exhausted or rate-limited
  (HTTP <code>)". A 403 breaks out of the retry loop immediately (no recovery → no wasted retries);
  a 429 retries at most once with backoff then gives up. Other HTTP errors keep the original 3×
  retry. The failure reason is stashed on `fetch_via_scraperapi.last_error`; `fetch()` propagates a
  distinguishable reason via `fetch.last_error` (e.g. "…credits exhausted… + direct blocked" vs the
  generic "Failed to fetch (ScraperAPI failed + direct blocked)"). `run()` now writes
  `fetch.last_error` to errors.csv instead of the hard-coded generic string, so credit exhaustion is
  actionable. Behavior otherwise intact (geo-blocked direct skip, Cloudflare guard, sleeps).
- **house730 documented stub** (resolution #2, spec §3a): Added `house730_rent` / `house730_buy`
  targets to `SCRAPE_TARGETS` (UNVERIFIED placeholder URLs, clearly commented, mirroring the 28hse
  district-page style) and a `parse_house730(html, listing_type)` registered in `PARSER_MAP`. The
  parser is a clearly-marked TODO stub: it logs a warning and returns `[]` (does NOT raise — raising
  would spam errors.csv and break the run). A top-of-function docstring explains it needs a live HTML
  sample and references spec §3a. Closes the README↔code gap without shipping an unverified parser.

### `.github/workflows/pages.yml` (created)
- **GitHub Pages deploy** (goal #3, resolution #3): Standard Pages deploy — `actions/checkout@v4`,
  `actions/configure-pages@v5`, `actions/upload-pages-artifact@v3` (uploads repo root `'.'`),
  `actions/deploy-pages@v4`. Triggered on push to default branch `main` AND `workflow_dispatch`.
  Permissions `contents: read`, `pages: write`, `id-token: write`. Concurrency group `pages` with
  `cancel-in-progress`. Uses the `github-pages` environment.

### `index.html` (created, repo root)
- **Root entry point** (resolution #3): Redirects to `dashboard.html` via meta refresh + JS
  `location.replace` fallback + a manual link. Lives at the site root so the dashboard's relative
  `data/*.csv` fetches keep working when Pages serves the repo root. dashboard.html NOT modified.

### `README.md` (modified)
- **Schedule fix** (resolution #4 — KEEP WEEKLY): Line ~45 now states the bot runs "every week on
  Saturdays at 08:00 HKT (00:00 UTC)" instead of "every day". Cron NOT changed.
- **Sources** (light touch): house730.com annotated as "wired but pending — parser is a documented
  stub awaiting a live HTML sample".

## Goal/resolution mapping
- Goal #2 / resolution #5 → three-message split + per-category empty messages + date header each.
- Resolution #1 → 403/429 detection, no-retry-on-403, clearer errors.csv strings.
- Resolution #2 → house730 wired target + stub parser (returns [], no raise).
- Goal #3 / resolution #3 → pages.yml + root index.html redirect; dashboard fetch logic untouched
  (verified relative `data/...` paths at dashboard.html:621-624).
- Resolution #4 → README weekly wording; cron left as `0 0 * * 6`.

## Syntax / validation commands run
- `python -c "import ast; ast.parse(open('scraper.py').read())"` → **PASS** (AST_PARSE_OK)
- `python -m py_compile scraper.py` → **PASS** (PY_COMPILE_OK; re-run after all edits, still PASS)
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/pages.yml'))"` → **PASS** (PAGES_YAML_OK)
- `index.html` fed through `html.parser` → **PASS** (INDEX_HTML_PARSE_OK)
- Confirmed `daily_scrape.yml` cron still `'0 0 * * 6'` and name still "HK Property Weekly Scrape".

## Deliberately NOT done (and why)
- Did NOT run `scraper.py` — it reads `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` via `os.environ[...]` at
  import time (would crash without creds) and makes live network calls. Used AST + py_compile per
  constraints.
- Did NOT change the cron or workflow name (resolution #4 says keep weekly).
- Did NOT modify dashboard.html fetch logic (verified it already uses relative `data/...` paths).
- Did NOT implement a real house730 parser (resolution #2 = DEFER; no live HTML sample offline).
- Did NOT touch requirements.txt (no new dependencies needed).
- Did NOT remove house730 from README.
- Did NOT fix the out-of-scope CSV data-quality bugs (spec §4).
- Did NOT commit or merge.
