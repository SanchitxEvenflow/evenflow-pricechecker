# Price Checker API

Scraper-first price checking service for **Amazon.in** and **Flipkart.in**. Pure request → scrape → return JSON — no database, no storage, no authentication.

## Tech Stack

- **Python 3.11+** with **FastAPI** + **Uvicorn**
- **requests** + **BeautifulSoup4** for Amazon.in scraping
- **Playwright** (async Chromium) for Flipkart.in scraping
- **Pydantic v2** for request/response validation
- Thread-safe proxy pool with round-robin rotation

## Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright Chromium browser (required once)
playwright install chromium

# Configure environment
cp .env.example .env

# Create proxy file (optional — works without proxies)
touch proxies.txt

# Run the server
uvicorn main:app --reload
```

Open `http://localhost:8000/docs` for the interactive Swagger UI.

## API Endpoints

### `POST /price/amazon`

Check price on Amazon.in by ASIN.

```json
{ "asin": "B0CHX3QBRQ" }
```

### `POST /price/flipkart`

Check price on Flipkart.in by FSN.

```json
{ "fsn": "HSPG3YAHYTJNGUXR" }
```

### `POST /price/both`

Check both platforms in parallel and get price comparison.

```json
{ "asin": "B0CHX3QBRQ", "fsn": "HSPG3YAHYTJNGUXR" }
```

### `GET /health`

Service health check — proxy pool size, Playwright browser status.

## Proxy Configuration

Add proxies to `proxies.txt`, one per line:

```text
http://user:pass@ip:port
http://ip:port
```

- Lines starting with `#` are treated as comments
- Empty lines are skipped
- If no proxies are configured, requests are made directly
- Proxies with 2+ failures are moved to a dead pool with 10-minute cooldown

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PROXY_FILE` | `proxies.txt` | Path to proxy list file |
| `AMAZON_DELAY_MIN` | `3.0` | Min delay (seconds) before Amazon requests |
| `AMAZON_DELAY_MAX` | `7.0` | Max delay (seconds) before Amazon requests |
| `FLIPKART_DELAY_MIN` | `4.0` | Min delay (seconds) before Flipkart requests |
| `FLIPKART_DELAY_MAX` | `9.0` | Max delay (seconds) before Flipkart requests |
| `PLAYWRIGHT_HEADLESS` | `true` | Run Playwright browser in headless mode |
| `LOG_LEVEL` | `INFO` | Logging level |
