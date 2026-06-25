# TESTER — Results

**Stage:** TESTER. Verifies the `ship/scraper-telegram-dashboard` changes WITHOUT live network / real credentials.

## OVERALL VERDICT: **PASS** — safe to proceed to review.

All 40 functional assertions passed, plus all compile/parse checks. No live network calls, no real Telegram/ScraperAPI usage (everything stubbed/monkeypatched). One non-blocking documentation nit noted below.

---

## Summary table

| # | Test | Result |
|---|------|--------|
| 1 | `py_compile scraper.py` | PASS |
| 1 | YAML load `pages.yml` + `daily_scrape.yml` | PASS |
| 1 | HTML parse `index.html` + `dashboard.html` | PASS |
| 2a | Builders emoji headers (ME / CLIENT / BUY) | PASS |
| 2a | Builders return `""` for `[]` | PASS |
| 2b | `run()` sends ≥3 messages | PASS |
| 2b | Each category header appears in exactly one message | PASS |
| 2b | Each category message carries date header "HK Property Daily Report" | PASS |
| 2b | Empty categories send "No new listings" message | PASS |
| 2b | Error message sent as separate 4th send on failures | PASS |
| 3 | `parse_28hse` extracts price/size/rooms | PASS |
| 3 | `parse_centanet` extracts price/size/rooms/district | PASS |
| 3 | `parse_ricacorp` extracts price/size/rooms | PASS |
| 3 | `parse_house730` returns `[]` + logs warning (stub) | PASS |
| 4 | ScraperAPI 403 → no retry (1 call), "credits exhausted" | PASS |
| 4 | ScraperAPI 429 → limited retries (2 calls), distinct msg | PASS |
| 4 | ScraperAPI 500 → full 3 retries | PASS |
| 4 | `fetch()` propagates credits-exhausted reason to `fetch.last_error` | PASS |
| 5 | `filter_rental_me` accept/reject (location/size/rooms) | PASS |
| 5 | `filter_rental_client` accept + reject size>800 | PASS |
| 5 | `filter_buy` accept 荃灣 + reject non-target location | PASS |
| 6 | `_parse_hk_price` 5 cases | PASS |

**Totals:** harness 1 = 30/30 PASS; harness 2 (ScraperAPI) = 10/10 PASS; compile/parse = all PASS. **0 FAIL, 0 SKIPPED.**

---

## Details

### Test 1 — Syntax / compile / parse
- `python3 -m py_compile scraper.py` → PY_COMPILE_OK.
- `yaml.safe_load` on `.github/workflows/pages.yml` and `daily_scrape.yml` → both load.
- `html.parser` on `index.html` and `dashboard.html` → both parse.

### Test 2 — Three distinct messages (goal #2, core)
- Builders verified directly: `🏠 *RENTAL — ME*`, `👤 *RENTAL — CLIENT*`, `🏢 *BUY / TRANSACTIONS*` headers present; all three return `""` on `[]`.
- `run()` driven with `fetch` monkeypatched to return `""`, `tg_send` recording into a list, `time.sleep`/`append_rows`/`log_error`/`load_seen_ids` stubbed. Result: exactly 3 category messages (each header in exactly one message, each containing the `📊 HK Property Daily Report — <date>` header), each empty category produced the "No new listings matching your criteria today." message, and a 4th `⚠️ SCRAPE ERRORS` message was sent. run() WAS drivable offline — no fallback needed.
- Note on the empty path: returning `""` from `fetch` trips the empty-shell guard (`scraper.py:1058`, `len(html) < 500`) before any parser runs, so every target yields no listings → all 3 categories empty → 3 "no new listings" sends. This correctly exercises resolution #5.

### Test 3 — Parsers regression
- Synthetic HTML mirroring each docstring. `parse_28hse` → `HKD 41,000` / size 920 / 3 rooms. `parse_centanet` → `HKD 48,000` / size 845 / 3 rooms / district 美孚. `parse_ricacorp` → `HKD 3,650,000` (from `$365萬`) / size 720 / 3 rooms. `parse_house730("<html></html>")` → `[]` and emits the STUB warning.

### Test 4 — ScraperAPI 403/429/500 handling
- `requests.get` inside `fetch_via_scraperapi` monkeypatched to raise `HTTPError` with a fake `.response.status_code`; `time.sleep` no-op'd.
- **403:** exactly 1 call (breaks immediately, `scraper.py:285-287`), `last_error` = "ScraperAPI credits exhausted or rate-limited (HTTP 403)".
- **429:** exactly 2 calls then gives up (`:288-290`), distinct rate-limited message.
- **500:** full 3 calls (generic retry path), `last_error` = "ScraperAPI HTTP 500".
- `fetch()` on a non-geo domain with a 403 + direct blocked propagates "...credits exhausted... + direct blocked" to `fetch.last_error` (`:355-356`), which `run()` writes to errors.csv (`:1051-1054`). Actionable, per resolution #1.

### Test 5 — Filters
- `filter_rental_me`: accepts 美孚/950sqft/3rm; rejects wrong location (天后), size<900, rooms<3.
- `filter_rental_client`: accepts 元朗/700sqft/3rm; rejects size>800.
- `filter_buy`: accepts 荃灣/1000sqft/3rm; rejects 中環 (non-target).

### Test 6 — Price helper
- `$880萬`→`HKD 8,800,000`; `$1,250萬`→`HKD 12,500,000`; `$41,000 元`→`HKD 41,000`; `HK$48,000`→`HKD 48,000`; `$3,650,000`→`HKD 3,650,000`. All match.

---

## Cross-checks (spec coverage, non-test)
- Dashboard fetches relative `data/*.csv` (`dashboard.html:624`) — compatible with Pages root deploy; loader unchanged. PASS.
- `pages.yml` triggers on push to `main` + workflow_dispatch, uploads `'.'`, permissions `pages: write` + `id-token: write`. Matches resolution #3.
- `index.html` redirects to `dashboard.html` (meta refresh + JS fallback). Matches resolution #3.
- `daily_scrape.yml` cron still `'0 0 * * 6'`, name still "HK Property Weekly Scrape" — unchanged per resolution #4.
- README line 45 now "every week on Saturdays at 08:00 HKT (00:00 UTC)".

## Non-blocking note (NOT a failure)
- `README.md:3` still opens with "A daily scraper ... sends ... every morning", contradicting the corrected weekly wording on line 45. Cosmetic; does not affect behavior. Worth a one-line follow-up but does not block review.

---

## Commands run
```
python3 -m py_compile scraper.py
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/pages.yml')); yaml.safe_load(open('.github/workflows/daily_scrape.yml'))"
python3 -c "from html.parser import HTMLParser; ... feed index.html + dashboard.html"
python3 /tmp/test_scraper_harness.py     # tests 2,3,5,6 — 30/30 PASS
python3 /tmp/test_scraperapi.py          # test 4 — 10/10 PASS
```
Throwaway harnesses live in `/tmp` (not committed). No source files modified.
