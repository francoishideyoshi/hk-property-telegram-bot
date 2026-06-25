# REVIEWER — Code Review

**Stage:** REVIEWER. Critical review of `ship/scraper-telegram-dashboard` against `.pipeline/spec.md` (§6 OWNER RESOLUTIONS) + the three goals. No code modified.

## OVERALL VERDICT: **APPROVE WITH NITS**

All three goals are met and the owner resolutions are faithfully implemented. The run() flow is intact, the house730 stub is safe (returns `[]`, no raise), the ScraperAPI 403/429 handling is correct and does not break the 500-retry path or fetch()'s return contract, and `fetch.last_error` is read safely. There is one **must-fix-before-merge nit** (README:3 ↔ README:45 weekly/daily contradiction, already flagged by the tester) and a few minor/observational items below. None are blockers.

---

## Findings

### Goal #2 — Three distinct Telegram messages

- `scraper.py:1118-1147` — CONFIRM (correct): Exactly three category messages are built in the right order (RENTAL — ME, RENTAL — CLIENT, BUY / TRANSACTIONS), each prefixed with `date_header`, sent in order. Empty categories send a self-contained "No new listings…" message with the category emoji header. Error message still sent as a separate 4th `tg_send` (`:1149-1150`). Matches resolution #5.
- `scraper.py:1145-1147` — **minor (header-loss on chunk split):** Per-message chunking is `[msg[i:i+MAX] for i in range(0, len(msg), MAX)]`. If a category body exceeds 4000 chars, **only the first chunk carries the date header + category header**; subsequent chunks are a raw mid-listing slice with no header and no category identity. The prompt explicitly asked to flag this. It is unlikely in practice (4000 chars ≈ many listings) and is a graceful-degradation edge, not a correctness break, but a header-preserving / listing-boundary split would be more robust. → Suggested fix: chunk on listing boundaries (split on `"\n\n"`) and re-prepend `date_header` (+ category header) to each chunk. Acceptable to defer.
- `scraper.py:1116` & builders `:994,:1001,:1008` — **minor (pre-existing Markdown-injection risk, NOT newly introduced):** `parse_mode="Markdown"` with estate/title text interpolated raw into `*{estate}*` / `[View]({url})`. An estate name containing `*`, `_`, `[`, `]` can break Telegram Markdown parsing and cause `tg_send` to fail with HTTP 400 for that whole message. This risk **pre-existed** the change (same builders, same `parse_mode`, same `_fmt_listing` at `:973-988`) — the 3-message split did not introduce it, though it now means one bad estate name fails one *category* message rather than the single combined message. Per the prompt's instruction to flag only if newly introduced: **not newly introduced** — noting for owner awareness / future hardening (escape Markdown or switch to MarkdownV2 with escaping). Not a blocker.
- `scraper.py:1134` `MAX = 4000` — CONFIRM: under Telegram's 4096 limit; the date_header + body prefix fits.

### Goal #1 — Sources (house730 stub + ScraperAPI handling)

- `scraper.py:883-904` `parse_house730` — CONFIRM (correct & safe): returns `[]`, logs a warning, does **not** raise. Will not break run() or spam errors.csv. Docstring clearly marks it a TODO stub referencing spec §3a.
- `scraper.py:201-208` — CONFIRM: `house730_rent`/`house730_buy` placeholder URLs are clearly commented `# UNVERIFIED placeholder` with a block comment (`:195-200`) explaining they are best-guess/untrusted. Matches resolution #2.
- `scraper.py:275-307` — CONFIRM (correct): 403 breaks immediately (no wasted retries); 429 retries at most once then breaks (`:288-290`, `attempt >= 2`); all **other** HTTPErrors (incl. 500) fall through to the generic branch (`:291-293`) and keep the full 3× retry. The 500-retry path is preserved. fetch()'s return contract (`str` on success, `None` on failure) is unchanged — run() at `:1048-1055` still works.
- `scraper.py:256,278,312` `fetch_via_scraperapi.last_error` and `:333,345-358,363` `fetch.last_error` — CONFIRM (read safely): `fetch.last_error` is initialized at module load (`:363`) AND reset at the top of every `fetch()` call (`:333`), so run()'s read at `:1051` (`fetch.last_error or "…default…"`) is always safe even if unset, and the `or` fallback covers the empty-string case. Threading from `fetch_via_scraperapi.last_error` → `fetch.last_error` (`:340-358`) is correct, including the geo-blocked branch (`:345-347`).
- `scraper.py:294-296` — **minor (observational):** A ScraperAPI **timeout** sets `last_error = "ScraperAPI timeout"` but is NOT a 403/429, so it correctly takes the full retry path. Fine. Just noting the 403-on-`e.response` access at `:276` assumes `e.response` is non-None — for a `requests` `HTTPError` raised by `raise_for_status()` this is always populated, so safe; a hand-raised HTTPError without `.response` would `AttributeError`, but that path doesn't occur in production. Not a blocker.

### Goal #3 — GitHub Pages

- `.github/workflows/pages.yml` — CONFIRM (correct): action versions current (`checkout@v4`, `configure-pages@v5`, `upload-pages-artifact@v3`, `deploy-pages@v4`); permissions `pages: write` + `id-token: write` (+ `contents: read`); `concurrency: group pages, cancel-in-progress`; triggers `push` to `main` + `workflow_dispatch`; uses `github-pages` environment. Matches resolution #3.
- `index.html` — CONFIRM: meta-refresh + `location.replace` JS fallback + manual link to `dashboard.html`. Served from site root so dashboard's relative `data/*.csv` fetches (`dashboard.html:622-624`) keep working. dashboard.html unmodified.
- `.github/workflows/pages.yml:35` `path: '.'` — **minor (oversharing of internal docs):** Uploading repo ROOT publishes EVERYTHING: `dashboard.html`, `data/*.csv` (intended; owner approved public CSVs — OK), **but also** `scraper.py`, `.github/`, and critically **`.pipeline/` internal pipeline docs** (spec.md, changes.md, test-results.md, this review). The CSV/source exposure matches the owner's "public repo OK" decision, but `.pipeline/` internal docs being world-readable at `https://<site>/.pipeline/spec.md` is almost certainly unintended. → Suggested fix: either build a scoped artifact (copy only `index.html`, `dashboard.html`, `data/` into `_site/` and upload that), or add a `.pipeline/` exclusion. Note: this is a *visibility* nuance only — `.pipeline/` is already in the public repo if committed; Pages just makes it directly fetchable. Worth flagging to the owner; not a merge blocker.

### Resolution #4 — Weekly schedule

- `.github/workflows/daily_scrape.yml:1,6` — CONFIRM: name still "HK Property Weekly Scrape", cron still `'0 0 * * 6'` (Saturday). NOT changed, per resolution #4.
- `README.md:45` — CONFIRM: now "every week on Saturdays at 08:00 HKT (00:00 UTC)".
- `README.md:3` — **nit (MUST-FIX-BEFORE-MERGE):** still reads "A **daily** scraper … sends … **every morning**", directly contradicting the corrected weekly wording at `:45`. Tester flagged this too. Cosmetic, no behavioral impact, but it is a user-facing contradiction in the same doc. → Suggested fix: change line 3 to "A weekly scraper … sends … every Saturday morning" (or similar).

### General — correctness / security / dead code

- `scraper.py` run() flow `:1037-1155` — CONFIRM: unchanged scrape/filter/dedup loop; CSV writes guarded by truthy checks; no regressions introduced by the send-block rewrite.
- Security — CONFIRM: `SCRAPER_API_KEY` is passed only as a request param to ScraperAPI (`:260`) and is never logged or written to errors.csv. The `last_error` strings (`:278-298`) contain only HTTP codes / generic messages, never the key or full proxied URL with the key. errors.csv rows (`:1053`) carry `source`, `url` (the *target* site URL, not the ScraperAPI URL with the embedded key), and the sanitized error — no secret leakage. `tg_send` failures log the exception, not the token (`:233`). Good.
- `data/.gitkeep` + tracked CSVs, no `.gitignore` — CONFIRM: `data/*.csv` are not git-ignored, so `daily_scrape.yml` commits flow to Pages. Fine.
- No dead code introduced. The old "join into full_msg + char-chunk" block was fully replaced (no orphan left).

---

## Maps to goals

- **Goal #1 (full source coverage incl. house730):** **MET** (as scoped by resolution #1/#2). centanet/midland targets+parsers already existed; ScraperAPI credit-exhaustion is owner billing action (out of code scope), and code now detects 403/429 + writes actionable errors.csv. house730 is wired with a safe documented stub per the DEFER decision. The README↔code gap is closed.
- **Goal #2 (three distinct Telegram messages):** **MET.** Three ordered, self-contained, date-headered messages; empty categories send a "no new listings" message; error message separate. Only caveat: a >4000-char single category loses its header on overflow chunks (minor, unlikely).
- **Goal #3 (public dashboard via Pages):** **MET.** pages.yml + index.html redirect deploy the dashboard at site root with `data/` alongside; dashboard fetch logic untouched. Caveat: `path: '.'` over-publishes `.pipeline/` internal docs (minor; flag to owner).

## Action items before merge
1. **(nit, do it)** Fix `README.md:3` daily/morning → weekly/Saturday to match `:45`.
2. **(minor, owner call)** Decide whether `.pipeline/` should be excluded from the Pages artifact (scope `path:` to `_site/` or exclude). Recommend yes.
3. **(minor, defer ok)** Consider listing-boundary chunking that re-prepends the header, and Markdown escaping for estate names — both pre-existing/edge, safe to defer.
