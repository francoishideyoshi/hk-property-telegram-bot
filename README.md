# 🏠 HK Property Telegram Bot

A weekly scraper that monitors Hong Kong real estate listings and sends structured Telegram messages every Saturday morning.

## Sections

| Section | Locations | Size | Rooms |
|---|---|---|---|
| 🏠 Rental for Me | Mei Foo, Lai Chi Kok, Cheung Sha Wan, Nam Cheong, Olympic, Sham Shui Po | ≥900 sqft | ≥3 |
| 👤 Rental for Client | Yuen Long, Long Ping (Sol City) | 600–800 sqft | 2–3 |
| 🏢 Buy / Transactions | Above + Tsuen Wan, Tsuen Wan West | ≥900 sqft | ≥3 |

## Sources

- hk.centanet.com
- house730.com _(wired but pending — parser is a documented stub awaiting a live HTML sample)_
- 28hse.com
- ricacorp.com
- midland.com.hk

> **Geo-blocking**: All requests are routed via [ScraperAPI](https://www.scraperapi.com/) with `country_code=hk` to bypass geo-restrictions.

## Setup

### 1. Create a Telegram Bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow instructions
3. Copy your **bot token**
4. Get your **chat ID** by messaging [@userinfobot](https://t.me/userinfobot)

### 2. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret Name | Value |
|---|---|
| `TELEGRAM_TOKEN` | Your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID (number) |
| `SCRAPER_API_KEY` | Your ScraperAPI.com API key |

### 3. Enable Actions

Go to **Actions** tab → enable workflows if prompted.

The bot runs automatically **every week on Saturdays at 08:00 HKT** (00:00 UTC).
You can also trigger it manually via **Actions → Run workflow**.

## Local Testing

```bash
pip install -r requirements.txt
export TELEGRAM_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export SCRAPER_API_KEY="your_scraperapi_key"
python scraper.py
```

## CSV Data

The `data/` folder stores cumulative CSVs:

- `rental_me.csv` — daily scraped rentals for you
- `rental_client.csv` — daily scraped rentals for clients
- `buy_transactions.csv` — buy listings & transactions
- `errors.csv` — scrape errors log

Listings already seen are **never re-sent** (deduplicated by `listing_id`).
