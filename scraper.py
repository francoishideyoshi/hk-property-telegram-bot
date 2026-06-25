#!/usr/bin/env python3
"""
HK Property Daily Scraper — v4 (May 2026)

Key fixes vs v3:
- parse_ricacorp: URL pattern corrected to /en-hk/property/detail/
                  price/size/rooms/district extracted from card text
- parse_midland:  ScraperAPI premium=true + render=true (Cloudflare WAF)
- parse_28hse:    price regex now handles "售 $880萬" (buy listings)
                  also handles "售 $X,XXX,XXX 元" long-form
- parse_centanet: unit price regex tightened (was matching @ in estate names)
- fetch:          Midland uses premium ScraperAPI; others use plain proxy
"""

import os
import csv
import re
import time
import logging
import hashlib
import requests
from datetime import datetime, date
from typing import Optional
from urllib.parse import urlparse, unquote
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SCRAPER_API_KEY  = os.environ.get("SCRAPER_API_KEY", "")
SCRAPER_API_BASE = "https://api.scraperapi.com"

# Domains that are geo-blocked — skip direct fallback entirely
GEO_BLOCKED_DOMAINS = {"midland.com.hk", "www.midland.com.hk"}

# Domains that need ScraperAPI premium mode (Cloudflare/WAF)
PREMIUM_DOMAINS = {"midland.com.hk", "www.midland.com.hk"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}

CSV_FILES = {
    "rental_me":     "data/rental_me.csv",
    "rental_client": "data/rental_client.csv",
    "buy":           "data/buy_transactions.csv",
    "errors":        "data/errors.csv",
}

CSV_FIELDNAMES = [
    "listing_id", "date_scraped", "date_posted", "title",
    "estate", "district", "floor", "size_sqft", "rooms",
    "price", "unit_price", "sold_price", "views", "source", "url",
]

# ─────────────────────────────────────────────────────────
# LOCATION FILTERS
# ─────────────────────────────────────────────────────────
RENTAL_ME_LOCATIONS = [
    "美孚", "荔枝角", "長沙灣", "南昌", "奧運", "深水埗",
    "Mei Foo", "Lai Chi Kok", "Cheung Sha Wan", "Nam Cheong",
    "Olympic", "Sham Shui Po",
    # 28hse URL district group codes for these areas
    "dg26", "dg27", "dg28",
    # Ricacorp URL slug district markers
    "olympic-station", "cheung-sha-wan", "sham-shui-po",
    "lai-chi-kok", "mei-foo", "nam-cheong",
]
RENTAL_CLIENT_LOCATIONS = [
    "元朗", "朗屏", "Yuen Long", "Long Ping",
    "YOHO", "SOL CITY", "Sol City", "Yoho", "The YOHO",
    # 28hse URL code
    "dg47",
    # Ricacorp slug
    "yuen-long",
]
BUY_LOCATIONS = RENTAL_ME_LOCATIONS + RENTAL_CLIENT_LOCATIONS + [
    "荃灣", "荃灣西", "Tsuen Wan", "Tsuen Wan West",
    "tsuen-wan",
]

# All HK districts used for text-based district extraction
HK_DISTRICTS = [
    "美孚", "荔枝角", "長沙灣", "南昌", "奧運", "深水埗", "太子", "旺角",
    "油麻地", "佐敦", "尖沙咀", "紅磡", "土瓜灣", "何文田", "九龍塘",
    "石硤尾", "九龍灣", "觀塘", "黃大仙", "鑽石山", "彩虹", "牛頭角",
    "元朗", "朗屏", "錦田", "兆康", "荃灣", "荃灣西", "青衣", "沙田",
    "馬鞍山", "大埔", "屯門", "粉嶺", "上水", "東涌", "啟德", "康城",
    "將軍澳", "西貢", "西灣河", "鰂魚涌", "太古", "筲箕灣", "柴灣",
    "又一村", "黃竹坑", "香港仔", "薄扶林", "西環", "上環", "中環",
    "灣仔", "銅鑼灣", "天后", "馬灣", "愉景灣", "大圍",
]

# ─────────────────────────────────────────────────────────
# SCRAPE TARGETS
#
# 28hse: targeted district-group pages (dg26/dg28/dg47)
#        instead of the full /rent/apartment (16,929 listings)
# ─────────────────────────────────────────────────────────
SCRAPE_TARGETS = {
    # ── Centanet ─────────────────────────────────────────
    "centanet_rent_kowloon": {
        "url": "https://hk.centanet.com/findproperty/list/rent?district=KL",
        "source": "hk.centanet.com", "type": "rent",
    },
    "centanet_rent_newterritories": {
        "url": "https://hk.centanet.com/findproperty/list/rent?district=NT",
        "source": "hk.centanet.com", "type": "rent",
    },
    "centanet_buy_kowloon": {
        "url": "https://hk.centanet.com/findproperty/list/buy?district=KL",
        "source": "hk.centanet.com", "type": "buy",
    },
    "centanet_buy_newterritories": {
        "url": "https://hk.centanet.com/findproperty/list/buy?district=NT",
        "source": "hk.centanet.com", "type": "buy",
    },
    "centanet_txn": {
        "url": "https://hk.centanet.com/findproperty/list/transaction",
        "source": "hk.centanet.com", "type": "transaction",
    },
    # ── 28hse — targeted district pages ──────────────────
    "28hse_rent_shamshuipo": {
        "url": "https://www.28hse.com/rent/apartment/a2/dg26",
        "source": "28hse.com", "type": "rent",
    },
    "28hse_rent_olympic": {
        "url": "https://www.28hse.com/rent/apartment/a2/dg28",
        "source": "28hse.com", "type": "rent",
    },
    "28hse_rent_yuenlong": {
        "url": "https://www.28hse.com/rent/apartment/a3/dg47",
        "source": "28hse.com", "type": "rent",
    },
    "28hse_buy_shamshuipo": {
        "url": "https://www.28hse.com/buy/apartment/a2/dg26",
        "source": "28hse.com", "type": "buy",
    },
    "28hse_buy_olympic": {
        "url": "https://www.28hse.com/buy/apartment/a2/dg28",
        "source": "28hse.com", "type": "buy",
    },
    "28hse_buy_yuenlong": {
        "url": "https://www.28hse.com/buy/apartment/a3/dg47",
        "source": "28hse.com", "type": "buy",
    },
    # ── Ricacorp — targeted district pages ───────────────
    # These URLs return SSR HTML with listings visible in page source
    "ricacorp_rent_olympic": {
        "url": "https://www.ricacorp.com/en-hk/property/list/rent/olympic-station-hma-en",
        "source": "ricacorp.com", "type": "rent",
    },
    "ricacorp_rent_cswssp": {
        "url": "https://www.ricacorp.com/en-hk/property/list/rent/cheung-sha-wan-sham-shui-po-district-kowloon-scope-en",
        "source": "ricacorp.com", "type": "rent",
    },
    "ricacorp_rent_yuenlong": {
        "url": "https://www.ricacorp.com/en-hk/property/list/rent/yuen-long-district-new-territories-west-scope-en",
        "source": "ricacorp.com", "type": "rent",
    },
    "ricacorp_buy_olympic": {
        "url": "https://www.ricacorp.com/en-hk/property/list/buy/olympic-station-hma-en",
        "source": "ricacorp.com", "type": "buy",
    },
    "ricacorp_buy_cswssp": {
        "url": "https://www.ricacorp.com/en-hk/property/list/buy/cheung-sha-wan-sham-shui-po-district-kowloon-scope-en",
        "source": "ricacorp.com", "type": "buy",
    },
    "ricacorp_buy_yuenlong": {
        "url": "https://www.ricacorp.com/en-hk/property/list/buy/yuen-long-district-new-territories-west-scope-en",
        "source": "ricacorp.com", "type": "buy",
    },
    "ricacorp_buy_tsuen_wan": {
        "url": "https://www.ricacorp.com/en-hk/property/list/buy/tsuen-wan-belvedere-garden-district-new-territories-west-scope-en",
        "source": "ricacorp.com", "type": "buy",
    },
    # ── Midland (geo-blocked + Cloudflare → premium ScraperAPI) ──
    "midland_rent": {
        "url": "https://www.midland.com.hk/en/list/rent",
        "source": "midland.com.hk", "type": "rent",
    },
    "midland_buy": {
        "url": "https://www.midland.com.hk/en/list/buy",
        "source": "midland.com.hk", "type": "buy",
    },
    # ── house730 — WIRED BUT PENDING (resolution #2, spec §3a) ───
    # Documented stub: targets are registered so the source is visible/wired,
    # but parse_house730 is a TODO that returns [] until a live HTML sample is
    # available (the site is geo-blocked + likely WAF; no offline sample).
    # URLs below are UNVERIFIED best-guess district pages mirroring the 28hse
    # district-page style. Do NOT trust these until confirmed against a sample.
    "house730_rent": {
        "url": "https://www.house730.com/en-us/rent/t1/",  # UNVERIFIED placeholder
        "source": "house730.com", "type": "rent",
    },
    "house730_buy": {
        "url": "https://www.house730.com/en-us/buy/t1/",  # UNVERIFIED placeholder
        "source": "house730.com", "type": "buy",
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────
def tg_send(text: str):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(api_url, json=payload, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


# ─────────────────────────────────────────────────────────
# FETCH HELPERS
# ─────────────────────────────────────────────────────────
def _domain(url: str) -> str:
    return urlparse(url).netloc


def fetch_via_scraperapi(url: str, premium: bool = False, retries: int = 3) -> Optional[str]:
    """
    Proxy via ScraperAPI.
    - plain mode (default): fast, works for SSR sites (centanet, 28hse, ricacorp)
    - premium=True: residential proxies + JS rendering for Cloudflare-protected sites
    NOTE: render=true is NOT set for plain mode — it causes 500s on centanet/28hse.

    HTTP 403/429 from ScraperAPI signal that the account is out of credits or
    being rate-limited (resolution #1). We surface these distinctly so errors.csv
    is actionable, and we do NOT keep retrying a 403 (no recovery — wasted time).
    A 429 may be retried once with backoff. The "credits exhausted" condition is
    flagged on the function object so fetch() can build a clearer errors.csv string.
    """
    fetch_via_scraperapi.last_error = ""
    if not SCRAPER_API_KEY:
        return None

    params: dict = {"api_key": SCRAPER_API_KEY, "url": url}
    if premium:
        params["premium"] = "true"
        params["render"] = "true"
        params["country_code"] = "hk"

    delay = 10
    for attempt in range(1, retries + 1):
        try:
            timeout = 180 if premium else 120
            log.info(f"ScraperAPI {'premium ' if premium else ''}attempt {attempt}/{retries}: {url}")
            r = requests.get(SCRAPER_API_BASE, params=params, timeout=timeout)
            r.raise_for_status()
            log.info(f"ScraperAPI success (attempt {attempt}): {url}")
            return r.text
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code
            if code in (403, 429):
                fetch_via_scraperapi.last_error = (
                    f"ScraperAPI credits exhausted or rate-limited (HTTP {code})"
                )
                log.error(
                    f"ScraperAPI credits exhausted or rate-limited "
                    f"(HTTP {code}) (attempt {attempt}): {url}"
                )
                if code == 403:
                    # No recovery from a credits-exhausted 403 — stop retrying.
                    break
                # 429: allow a single backoff retry, then give up.
                if attempt >= 2:
                    break
            else:
                fetch_via_scraperapi.last_error = f"ScraperAPI HTTP {code}"
                log.warning(f"ScraperAPI HTTP {code} (attempt {attempt}): {url}")
        except requests.exceptions.Timeout:
            fetch_via_scraperapi.last_error = "ScraperAPI timeout"
            log.warning(f"ScraperAPI timeout (attempt {attempt}): {url}")
        except Exception as e:
            fetch_via_scraperapi.last_error = f"ScraperAPI error: {e}"
            log.warning(f"ScraperAPI error (attempt {attempt}): {e}")

        if attempt < retries:
            log.info(f"Retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2

    log.error(f"ScraperAPI failed after {retries} attempts: {url}")
    return None


# Tracks the most recent ScraperAPI failure reason so fetch()/run() can write a
# clearer errors.csv string (e.g. distinguish "credits exhausted" from generic).
fetch_via_scraperapi.last_error = ""


def fetch_direct(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.error(f"Direct fetch failed for {url}: {e}")
        return None


def fetch(url: str) -> Optional[str]:
    """
    Returns HTML on success, or None on failure.

    On failure, fetch.last_error holds a human-readable reason. When ScraperAPI
    reported a 403/429, that reason distinguishes "credits exhausted" from a
    generic block so run() can write an actionable errors.csv row (resolution #1).
    """
    fetch.last_error = ""
    domain = _domain(url)
    use_premium = domain in PREMIUM_DOMAINS
    html = fetch_via_scraperapi(url, premium=use_premium)
    if html:
        return html

    scraperapi_reason = fetch_via_scraperapi.last_error
    credits_exhausted = "credits exhausted" in scraperapi_reason

    if domain in GEO_BLOCKED_DOMAINS:
        log.error(f"Skipping direct fallback — '{domain}' is geo-blocked.")
        fetch.last_error = (
            scraperapi_reason or "ScraperAPI failed"
        ) + " + direct skipped (geo-blocked)"
        return None

    log.info(f"Falling back to direct fetch: {url}")
    html = fetch_direct(url)
    if html:
        return html

    if credits_exhausted:
        fetch.last_error = scraperapi_reason + " + direct blocked"
    else:
        fetch.last_error = "Failed to fetch (ScraperAPI failed + direct blocked)"
    return None


# Most recent fetch() failure reason (set on every fetch call).
fetch.last_error = ""


# ─────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────
def listing_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def safe_int(val) -> int:
    if not val:
        return 0
    try:
        cleaned = re.sub(r"[^\d]", "", str(val))
        return int(cleaned) if cleaned else 0
    except Exception:
        return 0


def location_match(text: str, locations: list) -> bool:
    t = text.lower().replace(" ", "")
    return any(loc.lower().replace(" ", "") in t for loc in locations)


def load_seen_ids(csv_path: str) -> set:
    seen = set()
    if not os.path.exists(csv_path):
        return seen
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seen.add(row.get("listing_id", ""))
    except Exception as e:
        log.warning(f"Could not load seen IDs from {csv_path}: {e}")
    return seen


def append_rows(csv_path: str, rows: list):
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDNAMES})


def log_error(source: str, url: str, error: str):
    os.makedirs("data", exist_ok=True)
    path = CSV_FILES["errors"]
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["timestamp", "source", "url", "error"])
        w.writerow([datetime.now().isoformat(), source, url, error])


def _find_district_in_text(text: str) -> str:
    """Scan text for the first known HK district name."""
    for loc in HK_DISTRICTS:
        if loc in text:
            return loc
    return ""


# ─────────────────────────────────────────────────────────
# PRICE HELPERS
# ─────────────────────────────────────────────────────────
def _parse_hk_price(raw: str) -> str:
    """
    Normalise HK property price strings to "HKD X,XXX,XXX".
    Handles:
      $880萬        → HKD 8,800,000
      $1,250萬      → HKD 12,500,000
      $41,000 元    → HKD 41,000
      $3,650,000    → HKD 3,650,000
      HK$48,000     → HKD 48,000
    """
    raw = raw.strip()
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*(萬)?", raw)
    if not m:
        return raw
    num = float(m.group(1).replace(",", ""))
    if m.group(2) == "萬":
        num *= 10000
    return f"HKD {int(num):,}"


# ─────────────────────────────────────────────────────────
# PARSERS
# ─────────────────────────────────────────────────────────

def parse_28hse(html: str, listing_type: str) -> list:
    """
    28hse real HTML structure:
        [prop-link stars]  /property-NNN
        [prop-link title]  /property-NNN  (same URL, longer text)
        N 分鐘/小時/天前 刊登
        [district]  /a2/dg28/di28-68
        [estate]    /a2/dg28/di28-68/c2560
        | 樓層 實用面積: NNN 呎 建築面積: NNN 呎
        [租|售] $XX,XXX 元   OR   [售] $XXX萬
        N 房 , N 浴室

    Price formats for buy:
        "售 $880萬"   "售 $1,250萬"   "售 $3,500,000 元"
    Price formats for rent:
        "租 $41,000 元"
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_urls: set = set()

    prop_re     = re.compile(r"/(rent|buy|sell)/apartment/property-(\d+)$", re.IGNORECASE)
    district_re = re.compile(r"/dg\d+/di\d+-\d+$")
    estate_re   = re.compile(r"/c\d+$")

    prop_anchors = [a for a in soup.find_all("a", href=True)
                    if prop_re.search(a.get("href", ""))]

    for anchor in prop_anchors:
        raw_href = anchor.get("href", "")
        href = ("https://www.28hse.com" + raw_href
                if not raw_href.startswith("http") else raw_href)
        href = href.split("?")[0]
        if href in seen_urls:
            continue
        seen_urls.add(href)

        # Walk up DOM to find container that has a district sibling
        container = anchor.parent
        for _ in range(8):
            if container is None:
                break
            if container.find("a", href=district_re):
                break
            container = container.parent
        if container is None:
            container = anchor.parent

        district_anchors = container.find_all("a", href=district_re)
        estate_anchors   = container.find_all("a", href=estate_re)
        district = district_anchors[0].get_text(strip=True) if district_anchors else ""
        estate   = estate_anchors[0].get_text(strip=True)   if estate_anchors else ""

        # Title = longest text among property links in container
        all_prop_links = container.find_all("a", href=re.compile(r"/property-\d+$"))
        title = max(
            (a.get_text(strip=True) for a in all_prop_links),
            key=len,
            default=anchor.get_text(strip=True),
        )

        ctext = container.get_text(" ", strip=True)

        # ── Price ──────────────────────────────────────────
        # Buy:  "售 $880萬"  "售 $1,250萬"  "售 $3,500,000 元"
        # Rent: "租 $41,000 元"
        price = ""
        price_m = re.search(
            r"[租售]\s*\$\s*([\d,]+(?:\.\d+)?)\s*(萬)?(?:\s*元)?",
            ctext
        )
        if price_m:
            price = _parse_hk_price(f"${price_m.group(1)}{price_m.group(2) or ''}")

        # ── Size (saleable preferred, fall back to gross) ──
        size_m = re.search(r"實用面積[：:]\s*([\d,]+)\s*呎", ctext)
        if not size_m:
            size_m = re.search(r"實用\s*([\d,]+)\s*呎", ctext)
        if not size_m:
            size_m = re.search(r"建築面積[：:]\s*([\d,]+)\s*呎", ctext)
        size = size_m.group(1).replace(",", "") if size_m else ""

        # ── Unit price ─────────────────────────────────────
        unit_m     = re.search(r"@\s*([\d.]+)\s*元", ctext)
        unit_price = f"@${unit_m.group(1)}/呎" if unit_m else ""

        # ── Rooms ──────────────────────────────────────────
        rooms_m = re.search(r"(\d+)\s*房", ctext)
        rooms   = rooms_m.group(1) if rooms_m else ""

        # ── Floor ──────────────────────────────────────────
        floor_m = re.search(r"(高層|中層|低層|頂層|地下)", ctext)
        floor   = floor_m.group(1) if floor_m else ""

        # ── Date posted ────────────────────────────────────
        date_m   = re.search(r"(\d+\s*(?:分鐘|小時|天)前)", ctext)
        date_str = date_m.group(1) if date_m else ""

        results.append({
            "listing_id":   listing_id(href),
            "date_scraped": date.today().isoformat(),
            "date_posted":  date_str,
            "title":        title,
            "estate":       estate,
            "district":     district,
            "floor":        floor,
            "size_sqft":    size,
            "rooms":        rooms,
            "price":        price,
            "unit_price":   unit_price,
            "sold_price":   "",
            "views":        "",
            "source":       "28hse.com",
            "url":          href,
        })

    log.info(f"  28hse parser: {len(results)} listings extracted")
    return results


def parse_centanet(html: str, listing_type: str) -> list:
    """
    Centanet is Vue SSR. Each listing is a single
    <a href='/findproperty/detail/...'>  whose inner text contains:
      "浪澄灣 9座 高層 A室 3房 (1套房) 奧運站 21年樓齡
       實用 845呎 @ $56 /呎 建築 1,119呎 @ $42 /呎 租 $ 48,000"
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_urls: set = set()

    detail_re = re.compile(r"/findproperty/detail/", re.IGNORECASE)
    cards = soup.find_all("a", href=detail_re)

    for card in cards:
        raw_href = card.get("href", "")
        href = ("https://hk.centanet.com" + raw_href
                if not raw_href.startswith("http") else raw_href)
        href = href.split("?")[0]
        if href in seen_urls:
            continue
        seen_urls.add(href)

        text = card.get_text(" ", strip=True)
        if not text or len(text) < 15:
            continue

        # ── Price ──────────────────────────────────────────
        # "租 $ 48,000"  "售 $ 5,200,000"  "售 $880萬"
        price = ""
        price_m = re.search(
            r"[租售]\s*\$\s*([\d,]+(?:\.\d+)?)\s*(萬)?",
            text
        )
        if price_m:
            price = _parse_hk_price(f"${price_m.group(1)}{price_m.group(2) or ''}")

        # ── Saleable area ──────────────────────────────────
        # "實用 845呎"  "實用面積 845呎"  "實用面積: 845 呎"
        size_m = re.search(r"實用[面積：:\s]*([\d,]+)\s*呎", text)
        size   = size_m.group(1).replace(",", "") if size_m else ""

        # ── Unit price: "@ $56 /呎" ─────────────────────
        # Use word-boundary check so we don't match estate names with @
        unit_m     = re.search(r"@\s*\$\s*([\d.]+)\s*/?\s*呎", text)
        unit_price = f"@${unit_m.group(1)}/呎" if unit_m else ""

        # ── Rooms ──────────────────────────────────────────
        rooms_m = re.search(r"(\d+)\s*房", text)
        rooms   = rooms_m.group(1) if rooms_m else ""

        # ── Floor ──────────────────────────────────────────
        floor_m = re.search(r"(高層|中層|低層|頂層|地下)", text)
        floor   = floor_m.group(1) if floor_m else ""

        # ── Estate from URL slug ──────────────────────────
        slug   = href.split("/detail/")[-1].split("?")[0]
        estate = unquote(slug.split("_")[0]).replace("-", " ")

        # ── District from card text ───────────────────────
        district = _find_district_in_text(text)

        results.append({
            "listing_id":   listing_id(href),
            "date_scraped": date.today().isoformat(),
            "date_posted":  "",
            "title":        estate,
            "estate":       estate,
            "district":     district,
            "floor":        floor,
            "size_sqft":    size,
            "rooms":        rooms,
            "price":        price,
            "unit_price":   unit_price,
            "sold_price":   "",
            "views":        "",
            "source":       "hk.centanet.com",
            "url":          href,
        })

    log.info(f"  Centanet parser: {len(results)} listings extracted")
    return results


def parse_ricacorp(html: str, listing_type: str) -> list:
    """
    Ricacorp SSR page.
    Confirmed listing URL pattern: /en-hk/property/detail/{slug}
    Confirmed card text format:
      "ESTATE NAME  N Room  N Hall  High/Medium/Low Floor Zone  Flat X
       Saleable  NNN  sq.ft.  @  $XX,XXX  $NNN萬"   (buy)
       "Saleable  NNN  sq.ft.  @  $XX,XXX  $XX,XXX/月"  (rent)

    District is embedded in the URL slug as {area}-hma-... or {area}-district-...
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_urls: set = set()

    detail_re = re.compile(r"/en-hk/property/detail/", re.IGNORECASE)
    cards = soup.find_all("a", href=detail_re)

    for card in cards:
        raw_href = card.get("href", "")
        href = ("https://www.ricacorp.com" + raw_href
                if not raw_href.startswith("http") else raw_href)
        href = href.split("?")[0]
        if href in seen_urls:
            continue
        seen_urls.add(href)

        text = card.get_text(" ", strip=True)
        if not text or len(text) < 10:
            continue

        # ── Price: last $ token is the total ──────────────
        # Buy:  "@ $14,038  $365萬"   → last = "$365萬"
        # Rent: "@ $35,000  $35,000/月" → last = "$35,000"
        all_price_tokens = re.findall(
            r"\$\s*([\d,]+(?:\.\d+)?)\s*(萬)?(?:/月)?", text
        )
        price = ""
        if all_price_tokens:
            last_tok = all_price_tokens[-1]
            price = _parse_hk_price(f"${last_tok[0]}{last_tok[1]}")

        # ── Unit price: first @ token ──────────────────────
        unit_m     = re.search(r"@\s*\$\s*([\d,]+)", text)
        unit_price = f"@${unit_m.group(1)}/sq.ft." if unit_m else ""

        # ── Size: "Saleable NNN sq.ft." ───────────────────
        size_m = re.search(
            r"(?:Saleable|實用)\s*([\d,]+)\s*sq\.?ft\.?",
            text, re.IGNORECASE
        )
        if not size_m:
            size_m = re.search(r"([\d,]+)\s*sq\.?ft\.?", text, re.IGNORECASE)
        size = size_m.group(1).replace(",", "") if size_m else ""

        # ── Rooms ──────────────────────────────────────────
        rooms_m = re.search(r"(\d+)\s*(?:Room|Bed)", text, re.IGNORECASE)
        rooms   = rooms_m.group(1) if rooms_m else ""

        # ── Floor ──────────────────────────────────────────
        floor_m = re.search(
            r"(Very High|High|Medium|Low|Ground)\s*Floor",
            text, re.IGNORECASE
        )
        floor = (floor_m.group(1) + " Floor") if floor_m else ""

        # ── Estate = first non-empty line of card text ─────
        lines  = [l.strip() for l in text.split("\n") if l.strip()]
        estate = lines[0] if lines else text[:60]

        # ── District from URL slug ─────────────────────────
        # Pattern: /{district}-hma-{estate}-{code}-en
        #       or /{district}-district-...-scope-en
        slug = href.split("/detail/")[-1]
        hma_m = re.match(r"^([\w-]+?)-(?:hma|district)-", slug)
        district_slug = (
            hma_m.group(1).replace("-", " ").title() if hma_m else ""
        )

        # Also try to find a Chinese district name in the text
        district_cn = _find_district_in_text(text)

        # Prefer Chinese name; fall back to English slug
        district = district_cn or district_slug

        results.append({
            "listing_id":   listing_id(href),
            "date_scraped": date.today().isoformat(),
            "date_posted":  "",
            "title":        estate,
            "estate":       estate,
            "district":     district,
            "floor":        floor,
            "size_sqft":    size,
            "rooms":        rooms,
            "price":        price,
            "unit_price":   unit_price,
            "sold_price":   "",
            "views":        "",
            "source":       "ricacorp.com",
            "url":          href,
        })

    log.info(f"  Ricacorp parser: {len(results)} listings extracted")
    return results


def parse_midland(html: str, listing_type: str) -> list:
    """
    Midland is served behind Cloudflare via ScraperAPI premium.
    Their listing detail URLs follow /en/property/NNN or /en/list/detail/NNN.
    We search generically for any /en/ detail pattern, then parse card text.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_urls: set = set()

    # Midland detail URL patterns (multiple possible)
    detail_re = re.compile(
        r"/en/(?:property/|list/)?detail/",
        re.IGNORECASE
    )
    cards = soup.find_all("a", href=detail_re)

    if not cards:
        # Fallback: any anchor whose href has a long numeric/slug path under /en/
        fallback_re = re.compile(r"/en/(?:property|residential|flat)/[a-z0-9-]{8,}", re.IGNORECASE)
        cards = soup.find_all("a", href=fallback_re)

    for card in cards:
        raw_href = card.get("href", "")
        href = ("https://www.midland.com.hk" + raw_href
                if not raw_href.startswith("http") else raw_href)
        href = href.split("?")[0]
        if href in seen_urls or len(href) < 25:
            continue
        seen_urls.add(href)

        # Walk up to container with price info
        container = card.parent
        for _ in range(6):
            if container is None:
                break
            ct = container.get_text(" ", strip=True)
            if re.search(r"(?:HK)?\$[\d,]+|\d+\s*(?:sq|呎|房)", ct, re.IGNORECASE):
                break
            container = container.parent
        if container is None:
            container = card.parent

        ctext = container.get_text(" ", strip=True)

        # Price
        all_price_tokens = re.findall(
            r"\$\s*([\d,]+(?:\.\d+)?)\s*(萬)?(?:/月)?", ctext
        )
        price = ""
        if all_price_tokens:
            last_tok = all_price_tokens[-1]
            price = _parse_hk_price(f"${last_tok[0]}{last_tok[1]}")

        # Size
        size_m = re.search(
            r"([\d,]+)\s*(?:sq\.?ft\.?|呎)", ctext, re.IGNORECASE
        )
        size = size_m.group(1).replace(",", "") if size_m else ""

        # Rooms
        rooms_m = re.search(
            r"(\d+)\s*(?:bed|Bed|room|Room|房)", ctext
        )
        rooms = rooms_m.group(1) if rooms_m else ""

        # Floor
        floor_m = re.search(
            r"(Very High|High|Medium|Low|Ground)\s*Floor|"
            r"(高層|中層|低層|頂層|地下)",
            ctext, re.IGNORECASE
        )
        floor = floor_m.group(0) if floor_m else ""

        # Estate / title
        title_el = container.select_one(
            "h3, h2, h4, "
            "[class*='title'], [class*='name'], [class*='estate'], [class*='property']"
        )
        title = (
            title_el.get_text(strip=True)
            if title_el else card.get_text(strip=True)[:80]
        )

        # District
        dist_el = container.select_one(
            "[class*='district'], [class*='location'], [class*='region'], [class*='address']"
        )
        district = dist_el.get_text(strip=True) if dist_el else ""
        if not district:
            district = _find_district_in_text(ctext)

        results.append({
            "listing_id":   listing_id(href),
            "date_scraped": date.today().isoformat(),
            "date_posted":  "",
            "title":        title,
            "estate":       title,
            "district":     district,
            "floor":        floor,
            "size_sqft":    size,
            "rooms":        rooms,
            "price":        price,
            "unit_price":   "",
            "sold_price":   "",
            "views":        "",
            "source":       "midland.com.hk",
            "url":          href,
        })

    log.info(f"  Midland parser: {len(results)} listings extracted")
    return results


def parse_house730(html: str, listing_type: str) -> list:
    """
    TODO STUB — house730.com parser is intentionally unimplemented.

    Per resolution #2 (spec §3a, OPEN QUESTION #1): writing a correct house730
    parser requires a live HTML sample fetched through a working ScraperAPI key
    (the site is geo-blocked + likely WAF-protected), which is not available
    offline. Shipping a speculative parser would either silently produce garbage
    rows or raise and spam errors.csv on every run.

    This stub closes the README↔code gap — house730 is now registered and visible
    in SCRAPE_TARGETS / PARSER_MAP — without shipping an unverified parser.

    It deliberately does NOT raise: returning [] keeps the run green. Replace the
    body with a real container-walk parser (mirror parse_28hse) once a sample HTML
    is captured. See SCRAPE_TARGETS "house730_*" (UNVERIFIED placeholder URLs).
    """
    log.warning(
        "  house730 parser: STUB — not yet implemented "
        "(needs live HTML sample; see spec §3a). Returning 0 listings."
    )
    return []


PARSER_MAP = {
    "hk.centanet.com": parse_centanet,
    "28hse.com":       parse_28hse,
    "ricacorp.com":    parse_ricacorp,
    "midland.com.hk":  parse_midland,
    "house730.com":    parse_house730,  # documented TODO stub (resolution #2)
}


# ─────────────────────────────────────────────────────────
# FILTERS
#
# If a field is unparseable (returns 0), skip that check —
# don't falsely reject listings where we failed to extract.
# ─────────────────────────────────────────────────────────

def _search_text(listing: dict) -> str:
    """All text fields + URL combined for location matching."""
    return " ".join([
        listing.get("estate",   ""),
        listing.get("district", ""),
        listing.get("title",    ""),
        listing.get("url",      ""),
    ])


def filter_rental_me(listing: dict) -> bool:
    if not location_match(_search_text(listing), RENTAL_ME_LOCATIONS):
        return False
    size  = safe_int(listing.get("size_sqft"))
    if size and size < 900:
        return False
    rooms = safe_int(listing.get("rooms"))
    if rooms and rooms < 3:
        return False
    return True


def filter_rental_client(listing: dict) -> bool:
    if not location_match(_search_text(listing), RENTAL_CLIENT_LOCATIONS):
        return False
    size  = safe_int(listing.get("size_sqft"))
    if size and not (600 <= size <= 800):
        return False
    rooms = safe_int(listing.get("rooms"))
    if rooms and not (2 <= rooms <= 3):
        return False
    return True


def filter_buy(listing: dict) -> bool:
    if not location_match(_search_text(listing), BUY_LOCATIONS):
        return False
    size  = safe_int(listing.get("size_sqft"))
    if size and size < 900:
        return False
    rooms = safe_int(listing.get("rooms"))
    if rooms and rooms < 3:
        return False
    return True


# ─────────────────────────────────────────────────────────
# TELEGRAM MESSAGE BUILDERS
# ─────────────────────────────────────────────────────────

def _fmt_listing(i: int, l: dict, show_unit_price: bool = False) -> str:
    views_str  = f" · 👁 {l['views']}" if l.get("views") else ""
    posted_str = f" · 📅 {l['date_posted']}" if l.get("date_posted") else ""
    floor_str  = f" {l['floor']}" if l.get("floor") else ""
    unit_str   = f" ({l['unit_price']})" if show_unit_price and l.get("unit_price") else ""
    rooms_str  = f"🛏 {l.get('rooms', '?')} rooms" if l.get("rooms") else ""
    size_str   = f"📐 {l.get('size_sqft', '?')} sqft{floor_str}" if l.get("size_sqft") else floor_str
    price_str  = l.get("price") or "N/A"

    return (
        f"*{i}. {l.get('estate') or l.get('title') or 'N/A'}*\n"
        f"📍 {l.get('district', 'N/A')}  {size_str}  {rooms_str}\n"
        f"💰 {price_str}{unit_str}\n"
        f"🔗 [View]({l['url']})  📌 {l.get('source', '')}"
        f"{posted_str}{views_str}"
    )


def build_message_rental_me(listings: list) -> str:
    if not listings:
        return ""
    header = "🏠 *RENTAL — ME* (美孚 · 荔枝角 · 長沙灣 · 南昌 · 奧運 · 深水埗)\n"
    return header + "\n\n".join(_fmt_listing(i + 1, l) for i, l in enumerate(listings))


def build_message_rental_client(listings: list) -> str:
    if not listings:
        return ""
    header = "👤 *RENTAL — CLIENT* (元朗 · 朗屏 · YOHO / Sol City)\n"
    return header + "\n\n".join(_fmt_listing(i + 1, l) for i, l in enumerate(listings))


def build_message_buy(listings: list) -> str:
    if not listings:
        return ""
    header = "🏢 *BUY / TRANSACTIONS* (美孚 · 荔枝角 · 荃灣 · 元朗 · 朗屏)\n"
    return header + "\n\n".join(
        _fmt_listing(i + 1, l, show_unit_price=True) for i, l in enumerate(listings)
    )


def build_error_message(errors: list) -> str:
    if not errors:
        return ""
    lines = ["⚠️ *SCRAPE ERRORS*\n"]
    for source, url, err in errors:
        lines.append(f"❌ *{source}*\n`{url}`\n_{err[:200]}_")
    return "\n\n".join(lines)


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def run():
    today  = date.today().isoformat()
    errors = []

    seen_me     = load_seen_ids(CSV_FILES["rental_me"])
    seen_client = load_seen_ids(CSV_FILES["rental_client"])
    seen_buy    = load_seen_ids(CSV_FILES["buy"])

    new_me, new_client, new_buy = [], [], []

    for key, target in SCRAPE_TARGETS.items():
        url    = target["url"]
        source = target["source"]
        ltype  = target["type"]
        parser = PARSER_MAP.get(source)

        if not parser:
            log.warning(f"No parser for source '{source}', skipping {key}")
            continue

        log.info(f"Fetching {key} ({url})")
        html = fetch(url)

        if html is None:
            err_msg = fetch.last_error or "Failed to fetch (ScraperAPI exhausted + direct blocked)"
            log.error(f"{key}: {err_msg}")
            errors.append((source, url, err_msg))
            log_error(source, url, err_msg)
            continue

        # Detect Cloudflare challenge or empty shell
        if len(html) < 500 or "Just a moment" in html or "cf-browser-verification" in html:
            err_msg = "Cloudflare/bot-protection page — no usable content"
            log.warning(f"{key}: {err_msg}")
            errors.append((source, url, err_msg))
            log_error(source, url, err_msg)
            continue

        try:
            listings = parser(html, ltype)
        except Exception as e:
            err_msg = f"Parse error: {e}"
            log.error(f"{key}: {err_msg}", exc_info=True)
            errors.append((source, url, err_msg))
            log_error(source, url, err_msg)
            continue

        log.info(f"{key}: {len(listings)} raw listings extracted")

        matched_me = matched_cl = matched_buy = 0

        if ltype in ("rent",):
            for l in listings:
                lid = l["listing_id"]
                if lid not in seen_me and filter_rental_me(l):
                    new_me.append(l)
                    seen_me.add(lid)
                    matched_me += 1
                if lid not in seen_client and filter_rental_client(l):
                    new_client.append(l)
                    seen_client.add(lid)
                    matched_cl += 1

        if ltype in ("buy", "transaction"):
            for l in listings:
                lid = l["listing_id"]
                if lid not in seen_buy and filter_buy(l):
                    new_buy.append(l)
                    seen_buy.add(lid)
                    matched_buy += 1

        log.info(
            f"{key}: matched → me={matched_me} client={matched_cl} buy={matched_buy}"
        )
        time.sleep(3)

    # ── Save CSVs ─────────────────────────────────────────
    if new_me:
        append_rows(CSV_FILES["rental_me"], new_me)
    if new_client:
        append_rows(CSV_FILES["rental_client"], new_client)
    if new_buy:
        append_rows(CSV_FILES["buy"], new_buy)

    # ── Send Telegram — THREE distinct, self-contained messages ───
    # One message per category, in order: RENTAL — ME, RENTAL — CLIENT,
    # BUY / TRANSACTIONS. Each carries its own date header so it stands alone.
    # Empty categories still get a short "no new listings" message so the owner
    # always receives all three (resolution #5).
    date_header = f"📊 *HK Property Daily Report — {today}*\n{'─' * 34}\n"

    categories = [
        # (emoji header for the empty-state message, built body)
        (
            "🏠 *RENTAL — ME* (美孚 · 荔枝角 · 長沙灣 · 南昌 · 奧運 · 深水埗)",
            build_message_rental_me(new_me),
        ),
        (
            "👤 *RENTAL — CLIENT* (元朗 · 朗屏 · YOHO / Sol City)",
            build_message_rental_client(new_client),
        ),
        (
            "🏢 *BUY / TRANSACTIONS* (美孚 · 荔枝角 · 荃灣 · 元朗 · 朗屏)",
            build_message_buy(new_buy),
        ),
    ]

    MAX = 4000
    for empty_header, body in categories:
        if body:
            msg = date_header + body
        else:
            msg = (
                date_header
                + empty_header
                + "\nNo new listings matching your criteria today."
            )
        # Per-message chunking to respect Telegram's 4096-char limit.
        for chunk in [msg[i: i + MAX] for i in range(0, len(msg), MAX)]:
            tg_send(chunk)
            time.sleep(1)

    if errors:
        tg_send(build_error_message(errors))

    log.info(
        f"Done. new_me={len(new_me)} new_client={len(new_client)} "
        f"new_buy={len(new_buy)} errors={len(errors)}"
    )


if __name__ == "__main__":
    run()
