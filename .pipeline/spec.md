# Feature Spec — HK Property Bot

_Stage: PLANNER. This file is the only output. No code was written._

## 1. Problem Statement

The repo owner wants three things:

1. **Full source coverage** — the scraper must reliably scrape ALL websites listed in `README.md` (centanet, house730, 28hse, ricacorp, midland). Past scrapes show failures; investigate and confirm.
2. **Three distinct Telegram messages** — after consolidating new listings, send THREE separate messages instead of the current single combined message:
   - 🏠 RENTAL — ME (美孚 · 荔枝角 · 長沙灣 · 南昌 · 奧運 · 深水埗)
   - 👤 RENTAL — CLIENT (元朗 · 朗屏 · YOHO / Sol City)
   - 🏢 BUY / TRANSACTIONS (美孚 · 荔枝角 · 荃灣 · 元朗 · 朗屏)
3. **Publicly viewable dashboard** — `dashboard.html` must be reachable from anywhere via GitHub Pages, reading the committed CSVs.

---

## 2. Current State / Root-Cause Analysis

### 2a. Per-source scrape health

README (`README.md:15-19`) lists 5 sources. Code coverage and observed health:

| Source | In `SCRAPE_TARGETS`? | Parser in `PARSER_MAP`? | Observed health (data/errors.csv) |
|---|---|---|---|
| hk.centanet.com | ✅ 5 targets (`scraper.py:111-130`) | ✅ `parse_centanet` (`:811`) | **FAILING** — all 5 targets failed 2026-05-16 & 2026-05-23 with "ScraperAPI exhausted + direct blocked" |
| house730.com | ❌ **none** | ❌ **none** | **NEVER SCRAPED** — 2 historical error rows (2026-04-29) reference `house730.com/en-us/rent/t1/`, but there is no current target or parser |
| 28hse.com | ✅ 6 targets (`:132-155`) | ✅ `parse_28hse` (`:812`) | Healthy — no errors in recent runs; 67 buy rows produced |
| ricacorp.com | ✅ 7 targets (`:158-185`) | ✅ `parse_ricacorp` (`:813`) | Mostly healthy — produces rows, but data quality is poor (see 2e) |
| midland.com.hk | ✅ 2 targets (`:187-194`) | ✅ `parse_midland` (`:814`) | **FAILING** — both targets failed 2026-05-16 & 2026-05-23 with "ScraperAPI exhausted + direct blocked" |

`errors.csv` source tally: centanet 17, midland 4, house730 2. Error window spans 2026-04-29 → 2026-05-23.

**Confirmed:** house730 has NO target and NO parser despite being in README. **Confirmed:** centanet (all targets) + midland failed the two most recent runs with ScraperAPI-exhausted. 28hse/ricacorp produced no errors those runs.

### 2b. Missing house730

`SCRAPE_TARGETS` (`scraper.py:109-195`) has no `house730_*` entries and `PARSER_MAP` (`:810-815`) has no `house730.com` key. The `run()` loop (`:945-947`) does `PARSER_MAP.get(source)` and logs `"No parser for source..."` then `continue` — so even if a target existed it would be skipped. house730 is effectively unsupported. The only house730 evidence is two stale error rows from a prior code version.

### 2c. Single-vs-three-message gap

`run()` builds three section strings (`scraper.py:1014-1018`) then **joins them into ONE `full_msg`** (`:1020-1029`) and chunks that single string at 4000 chars (`:1031-1034`). Result: one combined message (or several size-based chunks of it), NOT three semantically distinct messages. The per-section builders already exist and are reusable: `build_message_rental_me` (`:893`), `build_message_rental_client` (`:900`), `build_message_buy` (`:907`) — each already returns `""` for an empty list and carries its own header. The date header is currently a single shared preamble (`:1020`).

### 2d. Dashboard data-loading mechanism + deployment gap

`dashboard.html` is a self-contained static page. It loads data client-side via `fetch()` of **relative paths** (`dashboard.html:621-624`):
- `data/buy_transactions.csv`
- `data/rental_client.csv`
- `data/rental_me.csv`

It parses CSV in-browser (`parseCSV`, `:272`) and renders Chart.js charts + tables. **It does NOT read `errors.csv`.** Because it uses relative `fetch`, it works correctly when served as a static site whose root contains both `dashboard.html` and the `data/` folder — which is exactly how a GitHub Pages deploy from the repo root behaves. No code change to the loader is required for Pages; the CSVs just need to be committed and served alongside the HTML.

**Deployment gap:** There is no GitHub Pages workflow and no `index.html`. `.github/workflows/` contains only `daily_scrape.yml`. GitHub Pages serves `index.html` (or `README.md`) at the site root by default — `dashboard.html` would only be reachable at `/<repo>/dashboard.html`, not the root. There is also **no git remote configured locally** (`git remote -v` is empty), so "the repo is on GitHub" is an assumption to confirm.

### 2e. Daily-vs-weekly mismatch (and a data-quality note)

- `README.md:45` says "runs automatically every day at **08:00 HKT** (00:00 UTC)".
- `.github/workflows/daily_scrape.yml:1` is named "HK Property **Weekly** Scrape"; cron is `'0 0 * * 6'` (`:6`) = Saturdays only.

**Confirmed mismatch.** Either the schedule or the README is wrong.

**Data-quality bug observed (out of the 3 goals, but noted):** `rental_me.csv` contains a row with `price = "48,000萬"` (i.e. 480,000,000) for a rental — the centanet price regex (`scraper.py:535-540`) wrongly attached `萬` to a `$48,000` rent. Several CSV rows are list/estate/hot-estate index URLs with empty fields (e.g. `.../property/list/...`, `.../property/estate/...`, `Ricacorp Hot Estates`), meaning the ricacorp parser is capturing non-listing anchors. The dashboard masks this with value-range guards (`>1e5 && <6e8`, etc.) but the underlying CSVs are dirty. Flagged for the owner; see Out of Scope.

---

## 3. Proposed Changes (file-scoped)

### (a) Scraper source coverage incl. house730

- **`scraper.py` — house730:** Two options.
  - **Recommended default (DEFER, but stub cleanly):** Do NOT ship a speculative house730 parser. Writing a correct parser requires a live HTML sample fetched through ScraperAPI (geo + likely WAF), which is not available offline. Add a single, clearly-commented placeholder note near `SCRAPE_TARGETS`/`PARSER_MAP` documenting that house730 is intentionally unimplemented pending a sample, so it is not silently forgotten. No behavioral change.
  - **If owner provides a sample / wants it now:** add `house730_*` entries to `SCRAPE_TARGETS` (rent + buy district pages) and a `parse_house730` function registered in `PARSER_MAP`, mirroring the `parse_28hse` container-walk approach. See OPEN QUESTIONS.
- **`scraper.py` — centanet/midland failures:** see (b). No coverage gap there (targets + parsers exist); the failures are fetch-layer, not coverage.

### (b) ScraperAPI-exhausted failures — code vs non-code

Root cause string is "ScraperAPI exhausted + direct blocked", emitted at `scraper.py:953` when `fetch()` returns `None`. `fetch()` (`:280-290`) returns `None` when ScraperAPI fails AND (domain is geo-blocked OR direct also fails). "Exhausted" = ScraperAPI account out of credits (HTTP 403/429 from the proxy), which `fetch_via_scraperapi` (`:229-267`) treats as a normal HTTP error and retries 3× with backoff before giving up.

- **NOT a code fix (env/account):** ScraperAPI credit exhaustion is a billing/account issue. The `SCRAPER_API_KEY` secret must have available credits. No code change creates credits. The owner must top up / upgrade the ScraperAPI plan, or reduce request volume. **This is the most likely real cause of the centanet+midland failures** (note they failed on the *later, later-in-the-run* targets — consistent with credits running out partway through a run).
- **In-code improvements (do in `scraper.py`):**
  1. **Distinguish "out of credits" from transient errors** in `fetch_via_scraperapi` (`:254-259`): detect HTTP 403/429 and log/record a distinct `"ScraperAPI credits exhausted (HTTP <code>)"` message so `errors.csv` is actionable instead of a generic blob. Do NOT keep retrying a 403-credits response (wasted time + no recovery).
  2. **Order targets to spend credits on the highest-value sources first** (optional) and/or add a small env-configurable cap, so a credit shortfall degrades gracefully rather than blanking the back half of the run.
  3. **Tighten the Cloudflare/empty-shell guard** (`:960`) only if needed; currently fine.
  - These reduce confusion and wasted retries but **cannot** fix an empty ScraperAPI balance — that remains the owner's account action.

### (c) Split Telegram into 3 distinct sends

In `scraper.py run()` (`:1013-1034`), replace the "join sections into one `full_msg` + char-chunk" block with **three independent sends**, one per category, each preceded by (or prefixed with) the date header so each message is self-contained.

- Reuse existing builders `build_message_rental_me`, `build_message_rental_client`, `build_message_buy` (`:893-913`) unchanged — each already emits its own emoji header and returns `""` when empty.
- For each category, build the body; prepend the date header (`:1020`); if the resulting body is non-empty, `tg_send` it; respect Telegram's 4096-char limit by chunking **within each category** (keep the existing MAX-chunk logic but apply per-message, and split on listing boundaries if feasible).
- **Empty-section behavior (default):** if a category has no new listings, **send a short "no new listings" message for that category** so the owner always receives three messages and knows the run completed (vs. silence = "did it even run?"). The header line still identifies which category. This is a deliberate default; the alternative (skip empty categories) is in OPEN QUESTIONS.
- **Date header:** include it at the top of each of the three messages (e.g. `📊 HK Property Daily Report — <date>` + category header), so each stands alone.
- **Error message:** keep the separate `build_error_message` send (`:1036-1037`) as a 4th, error-only message (unchanged).
- `tg_send` (`:207`) is already a single-message helper — no signature change needed.

### (d) Dashboard + GitHub Pages deploy

- **New file `.github/workflows/pages.yml`:** add a GitHub Pages deploy workflow using `actions/configure-pages`, `actions/upload-pages-artifact` (upload the repo root, or a built `_site/`), and `actions/deploy-pages`, triggered on `push` to the default branch (and `workflow_dispatch`). Grant `pages: write` + `id-token: write`. This publishes `dashboard.html` + `data/*.csv` as a static site.
- **Root entry point:** the dashboard fetches `data/...` relative paths, so it must be served from the site root with `data/` alongside. Either (i) add a minimal `index.html` at repo root that redirects to / contains the dashboard, or (ii) rename/duplicate `dashboard.html` → `index.html` so Pages serves it at the site root. **Recommended:** add a tiny `index.html` redirect to `dashboard.html` (keeps `dashboard.html` as the canonical name) OR copy dashboard to `index.html` in the Pages build step. No change to the dashboard's fetch logic is required.
- **CSVs must be committed:** `daily_scrape.yml:36-42` already commits `data/*.csv` and pushes — so fresh data flows to Pages automatically after each run. Confirm `.gitignore` does not exclude `data/*.csv` (current `data/` contains tracked CSVs, so this is fine).
- **No change to dashboard JS required.** Optionally surface `errors.csv` in a future iteration (out of scope here).

### (e) Schedule mismatch (supporting fix)

Pick ONE of daily or weekly and make `README.md:45`, the workflow `name` (`daily_scrape.yml:1`), and the cron (`:6`) agree. Default proposed: **honor the README's stated intent (daily 00:00 UTC)** → change cron to `'0 0 * * *'` and rename the workflow to "HK Property Daily Scrape". See OPEN QUESTIONS — note daily runs ~7× the ScraperAPI usage of weekly, which interacts with the credit-exhaustion issue in (b).

---

## 4. Out of Scope / Assumptions

- **Out of scope:** Fixing CSV data-quality bugs (the `48,000萬` rent mis-parse; ricacorp capturing list/estate/hot-estate index anchors; empty-field rows). These are real but separate from the 3 stated goals; flagged for a follow-up. Re-scraping or back-cleaning historical CSV rows is out of scope.
- **Out of scope:** Adding `errors.csv` visualization to the dashboard; auth/private hosting for the dashboard; migrating off ScraperAPI.
- **Assumptions:** (1) The repo is/will be pushed to GitHub (no local git remote is currently configured). (2) `SCRAPER_API_KEY`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` secrets are configured in repo Actions secrets. (3) Telegram's per-message limit is 4096 chars; three category messages plus an optional error message are well within Telegram's rate limits with the existing inter-send `sleep`.

---

## 5. OPEN QUESTIONS

> Defaults are proposed where a safe one exists, so implementation can proceed without blocking. Items marked **[BLOCKING]** genuinely need the owner before that sub-feature can be completed correctly.

1. **house730 — implement now or defer?** A correct parser needs a live house730 HTML sample fetched via a working ScraperAPI key (the site is geo-blocked + likely WAF), which is not available offline. **Default: DEFER** with a documented stub (Proposed Change 3a). → **[BLOCKING for house730 only]** — full implementation cannot be verified without a sample or a working key. The rest of the feature proceeds regardless.

2. **Empty-section Telegram behavior — send "no new listings" or skip?** **Default: send a short per-category "no new listings" message** so all three messages always arrive (Proposed Change 3c). Non-blocking; flip to "skip empty" on owner preference.

3. **ScraperAPI credit exhaustion — is this an account/billing issue the owner must resolve?** Evidence strongly indicates yes: centanet+midland fail with "exhausted" on the later targets of recent runs. **Code cannot create credits.** → **[BLOCKING for reliable full-coverage]** — the owner must confirm the ScraperAPI plan has credits / top it up; otherwise centanet+midland will keep failing no matter what code ships. Code-side we will only improve error clarity and stop wasted retries.

4. **Daily vs weekly schedule — which is intended?** README says daily; workflow is weekly. **Default: daily (`0 0 * * *`)** to match README. Non-blocking, but note daily ≈ 7× ScraperAPI spend — interacts with Q3. Owner should confirm given credit constraints.

5. **GitHub Pages — is the repo PUBLIC, and is committing CSVs (data visible to anyone) acceptable?** GitHub Pages on a free account requires a **public** repo, which makes `data/*.csv` (estates, prices, URLs) publicly visible. **Default: assume public + CSVs are non-sensitive market data = acceptable.** → **[BLOCKING if the owner needs the data private]** — if the data must stay private, GitHub Pages (free tier) is not viable and an alternative host is needed. Also confirm a GitHub remote exists (none configured locally).

### BLOCKING summary
Yes — there ARE blocking items, but each is scoped to one sub-feature, not the whole spec:
- **Q3 (ScraperAPI credits)** blocks reliable full-coverage of centanet+midland — owner billing action required.
- **Q1 (house730 sample/key)** blocks the house730 parser only — deferrable.
- **Q5 (public repo + CSV visibility)** blocks GitHub Pages only if the data must remain private.

The Telegram 3-message split (goal 2) and the dashboard/Pages workflow plumbing (goal 3, given a public repo) have NO blocking unknowns and can be implemented immediately.

---

## 6. OWNER RESOLUTIONS (2026-06-25)

1. **ScraperAPI:** Owner will top up credits → code ALL sources. Code-side: add 403/429 credit-exhaustion detection, stop wasted retries, clearer errors.csv messages.
2. **house730:** DEFER. Add documented stub target + `parse_house730` raising NotImplementedError/clearly marked TODO, registered but skipped, so README↔code gap is closed without an unverified parser.
3. **GitHub Pages:** Public repo OK. Add `.github/workflows/pages.yml` + root `index.html` (redirect to dashboard.html). Deploy on push to default branch.
4. **Schedule:** KEEP WEEKLY (Saturday cron). Fix README to say weekly (not daily). Do NOT change cron.
5. **Empty Telegram section:** default kept — send a short per-category "no new listings" message so all THREE messages always arrive. Date header on each.
