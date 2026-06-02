# FastAPI Price Checker Prompt

Build a FastAPI price-checking service for Amazon.in and Flipkart.in. This is a scraper-first build — no database, no storage, no authentication required yet.

## Tech Stack

- Python 3.11+
- FastAPI + Uvicorn
- `requests` + `BeautifulSoup4` for Amazon.in
- `playwright` (async Chromium) for Flipkart.in — wrapped in `asyncio.run_in_executor` with `concurrent.futures.ThreadPoolExecutor` to avoid blocking FastAPI's async event loop
- `python-dotenv` for environment config
- `pydantic` v2 for request/response validation

## Project Structure

```text
price-checker/
├── main.py
├── scrapers/
│   ├── __init__.py
│   ├── amazon.py
│   └── flipkart.py
├── proxy/
│   ├── __init__.py
│   └── manager.py
├── schemas/
│   ├── __init__.py
│   └── price.py
├── utils/
│   ├── __init__.py
│   └── headers.py
├── proxies.txt
├── .env
├── requirements.txt
└── README.md
```

## Endpoints

### `POST /price/amazon`

- Input: `{ "asin": "B0CHX3QBRQ" }`
- Validate: ASIN must be exactly 10 alphanumeric characters — reject with HTTP 422 if invalid
- Returns:

```json
{
  "asin": "B0CHX3QBRQ",
  "price": "₹8,999",
  "mrp": "₹12,999",
  "status": "available",
  "platform": "amazon",
  "url": "https://www.amazon.in/dp/B0CHX3QBRQ",
  "checked_at": "2026-06-01T16:44:00"
}
```

### `POST /price/flipkart`

- Input: `{ "fsn": "HSPG3YAHYTJNGUXR" }`
- Validate: FSN must be exactly 16 alphanumeric characters — reject with HTTP 422 if invalid
- Returns:

```json
{
  "fsn": "HSPG3YAHYTJNGUXR",
  "price": "₹8,499",
  "mrp": "₹12,999",
  "discount": "34%",
  "status": "available",
  "platform": "flipkart",
  "url": "https://www.flipkart.com/product/p/fsn?fn=HSPG3YAHYTJNGUXR",
  "checked_at": "2026-06-01T16:44:02"
}
```

### `POST /price/both`

- Input: `{ "asin": "B0CHX3QBRQ", "fsn": "HSPG3YAHYTJNGUXR" }`
- Validate both ASIN and FSN formats before making any request
- Run both scrapers in parallel using `asyncio.gather`
- Returns:

```json
{
  "asin": "B0CHX3QBRQ",
  "fsn": "HSPG3YAHYTJNGUXR",
  "amazon": {
    "price": "₹8,999",
    "mrp": "₹12,999",
    "status": "available",
    "url": "https://www.amazon.in/dp/B0CHX3QBRQ",
    "checked_at": "2026-06-01T16:44:00"
  },
  "flipkart": {
    "price": "₹8,499",
    "mrp": "₹12,999",
    "discount": "34%",
    "status": "available",
    "url": "https://www.flipkart.com/product/p/fsn?fn=HSPG3YAHYTJNGUXR",
    "checked_at": "2026-06-01T16:44:02"
  },
  "price_diff": "₹500",
  "cheaper_on": "flipkart"
}
```

### `GET /health`

- Returns service status, proxy pool size, whether Playwright browser is ready

```json
{
  "status": "ok",
  "proxy_pool_size": 10,
  "playwright_ready": true,
  "timestamp": "2026-06-01T16:44:00"
}
```

## `scrapers/amazon.py` — Full Specification

- Use `requests.Session` — create a new session per ASIN request, do not share sessions
- Target URL: `https://www.amazon.in/dp/{ASIN}`
- Get proxy from `ProxyManager.get_proxy()` — inject as `session.proxies`. If proxy pool is empty, make direct request
- Build headers using `utils/headers.py` — rotate User-Agent on every call
- Parse HTML with BeautifulSoup4 using `html.parser`
- Extract **current selling price** using these CSS selectors in exact priority order:
  1. `#corePrice_feature_div span.a-offscreen`
  2. `.apexPriceToPay span.a-offscreen`
  3. `#price_inside_buybox`
  4. `#newBuyBoxPrice`
  5. `#tp_price_block_total_price_ww span.a-offscreen`
- Extract **MRP** from: `#corePriceDisplay_desktop_feature_div .a-text-price span.a-offscreen` or `.basisPrice span.a-offscreen`
- Status detection (check in this order before price extraction):
  - If response contains `captcha` or `robot check` → return status `"blocked"`, call `ProxyManager.report_failure(proxy)`
  - If `#availability` text contains `currently unavailable` / `out of stock` → return status `"unavailable"`
  - If canonical URL ASIN ≠ requested ASIN → return status `"suppressed"`
  - If `#productTitle` not found → return status `"not_found"`
  - If price found + buy button present → return status `"available"`
- On `"blocked"` status: call `ProxyManager.report_failure()`, retry once with next proxy after 5 second delay
- On successful response: call `ProxyManager.report_success(proxy)`
- Add `random.uniform(3.0, 7.0)` second delay before every request
- Timeout: 15 seconds on all requests
- Wrap entire function in try/except — never raise, always return a response dict with `status: "error"` and `message` field on exception

## `scrapers/flipkart.py` — Full Specification

- Use Playwright **async** API with Chromium in headless mode
- On app startup (FastAPI `lifespan`): launch one persistent Playwright browser instance, store in app state
- Per request: create a **new browser context** from the persistent browser (not a new browser)
- Browser launch args:

```text
--no-sandbox
--disable-blink-features=AutomationControlled
--disable-infobars
--window-size=1920,1080
```

- On every new page, inject this init script to hide automation:

```javascript
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
```

- Get proxy from `ProxyManager.get_proxy()` — pass to browser context as:

```python
context = await browser.new_context(
    proxy={"server": "http://ip:port", "username": "user", "password": "pass"},
    viewport={"width": 1920, "height": 1080},
    user_agent="Mozilla/5.0 ..."
)
```

- Navigate to: `https://www.flipkart.com/product/p/fsn?fn={FSN}`
- Wait for either `._30jeq3` (price selector) or `body` — timeout 20 seconds
- Check page content before extraction:
  - If body text contains `"Site is overloaded"` → report_failure, close context, retry once after 10s with new proxy
  - If body text contains `"page not found"` or `"404"` → return status `"not_found"`
- Extract **current price**: CSS selector `._30jeq3` — first match
- Extract **MRP**: CSS selector `._3I9_wc` or `._2p6lqe` — first match
- Extract **discount**: CSS selector `._3Ay6Sb span` or `._1V_ZGU span`
- Extract **availability**: if `._30jeq3` not found after page load → status `"unavailable"`
- Always close browser context in `finally` block — never leak contexts
- Add `random.uniform(4.0, 9.0)` second delay before navigation
- Wrap in try/except — never raise, always return response dict
- Run Playwright's sync-blocking calls inside `asyncio.run_in_executor` with a `ThreadPoolExecutor(max_workers=2)`

## `proxy/manager.py` — Full Specification

- On init: read `proxies.txt` line by line — skip empty lines and lines starting with `#`
- Expected proxy format per line: `http://user:pass@ip:port` or `http://ip:port`
- Internal state:

```python
active_pool: list[str]      # healthy proxies
dead_pool: dict[str, float] # proxy → timestamp when it died
failure_count: dict[str, int]
index: int                  # current round-robin position
```

- `get_proxy() -> str | None`:
  - Before returning, move any dead proxy back to active if it has been dead for > 600 seconds (10 min cooldown)
  - Return `active_pool[index % len(active_pool)]`, increment index
  - If `active_pool` is empty → return `None` (caller makes direct request and logs a warning)
- `report_failure(proxy: str)`:
  - Increment `failure_count[proxy]`
  - If `failure_count[proxy] >= 2` → remove from `active_pool`, add to `dead_pool` with current timestamp, log warning
- `report_success(proxy: str)`:
  - Reset `failure_count[proxy] = 0`
- `status() -> dict`: returns `{ active: N, dead: N, total: N }` — used by `/health` endpoint
- Thread-safe: use `threading.Lock` for all mutations to `active_pool` and `dead_pool`

## `utils/headers.py` — Full Specification

- Define a `UA_POOL` list of 8 real Chrome User-Agent strings (Windows + Mac + Linux variants, Chrome 120–124)
- `get_headers() -> dict`: returns a full browser header dict with a randomly selected UA:

```python
{
    "User-Agent": random.choice(UA_POOL),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "Referer": "https://www.google.co.in/"
}
```

## `schemas/price.py` — Full Specification

```python
class AmazonRequest(BaseModel):
    asin: str
    force_refresh: bool = False

    @field_validator("asin")
    def validate_asin(cls, v):
        v = v.strip().upper()
        if not re.match(r'^[A-Z0-9]{10}$', v):
            raise ValueError("ASIN must be exactly 10 alphanumeric characters")
        return v

class FlipkartRequest(BaseModel):
    fsn: str
    force_refresh: bool = False

    @field_validator("fsn")
    def validate_fsn(cls, v):
        v = v.strip().upper()
        if not re.match(r'^[A-Z0-9]{16}$', v):
            raise ValueError("FSN must be exactly 16 alphanumeric characters")
        return v

class BothRequest(BaseModel):
    asin: str
    fsn: str
    force_refresh: bool = False
    # Apply same validators as above for both fields

class AmazonResponse(BaseModel):
    asin: str
    price: str
    mrp: str | None
    status: str
    platform: str = "amazon"
    url: str
    checked_at: datetime

class FlipkartResponse(BaseModel):
    fsn: str
    price: str
    mrp: str | None
    discount: str | None
    status: str
    platform: str = "flipkart"
    url: str
    checked_at: datetime

class BothResponse(BaseModel):
    asin: str
    fsn: str
    amazon: AmazonResponse
    flipkart: FlipkartResponse
    price_diff: str | None
    cheaper_on: str | None
```

## `main.py` — Full Specification

- Use FastAPI `lifespan` context manager for startup/shutdown:
  - Startup: initialize `ProxyManager` (reads proxies.txt), launch Playwright browser, store both in `app.state`
  - Shutdown: close Playwright browser cleanly
- Register routers from `routes/price.py`
- Add CORS middleware (`allow_origins=["*"]` for demo)
- Global exception handler: catch unhandled exceptions, return `{ "status": "error", "message": str(e) }` with HTTP 500
- Log every incoming request: method, path, timestamp

## `.env` file

```text
PROXY_FILE=proxies.txt
AMAZON_DELAY_MIN=3.0
AMAZON_DELAY_MAX=7.0
FLIPKART_DELAY_MIN=4.0
FLIPKART_DELAY_MAX=9.0
PLAYWRIGHT_HEADLESS=true
LOG_LEVEL=INFO
```

## `requirements.txt`

```text
fastapi
uvicorn[standard]
requests
beautifulsoup4
playwright
python-dotenv
pydantic>=2.0
```

## Critical Constraints

1. Do NOT use ScraperAPI, Selenium, or any paid scraping service
2. Do NOT add any database or storage layer — pure request → scrape → return JSON only
3. Playwright must run in a thread pool executor, never directly in async context
4. Every scraper function must return a dict — never raise exceptions to the caller
5. If `proxies.txt` is empty or missing, fall back to direct connection silently — do not crash on startup
6. `playwright install chromium` must be run once manually after pip install — add this to README
7. Price strings must preserve the `₹` symbol and comma formatting exactly as seen on the page — do not convert to float
8. `checked_at` must be ISO 8601 format in IST timezone (`Asia/Kolkata`)

## Run Instructions

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
touch proxies.txt
uvicorn main:app --reload
```

Open `http://localhost:8000/docs` for the demo UI.
