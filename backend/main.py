"""
FastAPI Price Checker — Amazon.in & Flipkart.in scraper service.
"""

import asyncio
import itertools
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from auth import (
    LoginRequest,
    auth_enabled,
    create_token,
    is_public_route,
    verify_credentials,
    verify_token,
)

from proxy.manager import ProxyManager
from amazon.routes import price_router as amazon_price_router
from amazon.routes import sheets_router as amazon_sheets_router
from amazon.routes import manual_router as amazon_manual_router
from flipkart.routes import router as flipkart_price_router
from flipkart.routes import manual_router as flipkart_manual_router
from flipkart.routes import sheets_router as flipkart_sheets_router
from blinkit.routes import router as blinkit_router
from zepto.routes import router as zepto_router
from instamart.routes import router as instamart_router
from flipkart_minutes.routes import router as flipkart_minutes_router
from scheduler import setup_scheduler
from schemas.price import (
    AmazonResponse,
    BothRequest,
    BothResponse,
    FlipkartResponse,
    HealthResponse,
)

from amazon.scraper import scrape_amazon, fetch_curl_supplement, merge_curl_supplement
from flipkart.scraper import scrape_flipkart
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import SCRAPE_CONCURRENCY, MANUAL_RESERVED, BROWSER_POOL_SIZE, get_browser, sem_with_timeout

load_dotenv()

# ── Logging ─────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


# ── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    logger.info("Starting Price Checker service...")

    """Startup: init ProxyManager + launch Playwright browser. Shutdown: close browser."""
    # Monkey-patch IocpProactor.accept to prevent WinError 87 from killing the accept loop
    if sys.platform == "win32":
        import asyncio.windows_events as _aio_win_events
        _orig_accept = _aio_win_events.IocpProactor.accept
        def _patched_accept(self, listener):
            try:
                return _orig_accept(self, listener)
            except OSError as exc:
                if getattr(exc, "winerror", None) == 87:
                    logger.warning("Caught WinError 87 in accept(), faking ECONNABORTED to keep loop alive.")
                    # ECONNABORTED (10053) is caught and ignored by the loop, keeping it alive
                    raise OSError(0, "Connection aborted", None, 10053) from exc
                raise
        _aio_win_events.IocpProactor.accept = _patched_accept

    # Initialize proxy manager
    proxy_file = os.getenv("PROXY_FILE", "proxies.txt")
    app.state.proxy_manager = ProxyManager(proxy_file)
    app.state.proxy_manager_task = asyncio.create_task(app.state.proxy_manager.resurrect_loop())
    proxy_status = app.state.proxy_manager.status()
    logger.info("Proxy pool: %d active, %d dead", proxy_status["active"], proxy_status["dead"])

    zepto_proxy_file = os.getenv("ZEPTO_PROXY_FILE", "zepto_proxies.txt")
    app.state.zepto_proxy_manager = ProxyManager(zepto_proxy_file)
    app.state.zepto_proxy_manager_task = asyncio.create_task(app.state.zepto_proxy_manager.resurrect_loop())

    # Initialize Google Sheets client and Thread Pool
    # Size to cover simultaneous Blinkit + Zepto executor concurrency plus headroom.
    _blinkit_workers = int(os.getenv("BLINKIT_CONCURRENCY", "10"))
    _zepto_workers = int(os.getenv("ZEPTO_CONCURRENCY", "10"))
    _thread_pool_size = SCRAPE_CONCURRENCY * 3 + _blinkit_workers + _zepto_workers
    app.state.sheets_client = GoogleSheetsClient()
    app.state.thread_pool = ThreadPoolExecutor(max_workers=_thread_pool_size)

    # Launch Playwright browser pool
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
    playwright_instance = None
    _browser_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--window-size=1920,1080",
    ]

    try:
        from playwright.async_api import async_playwright
        from utils.browser_manager import BrowserPoolManager

        playwright_instance = await async_playwright().start()
        
        app.state.browser_manager = BrowserPoolManager(playwright_instance, BROWSER_POOL_SIZE, headless, _browser_args, max_requests=500)
        await app.state.browser_manager.launch_all()

        if not app.state.browser_manager.browsers:
            raise RuntimeError("No browsers launched — cannot start service")

        app.state.playwright_instance = playwright_instance
        app.state.playwright_ready = True
        
        from cachetools import TTLCache
        app.state.cache = TTLCache(maxsize=10000, ttl=7200)

    except Exception as e:
        logger.error("Failed to launch Playwright browser pool: %s", str(e))
        app.state.playwright_instance = None
        app.state.browser_manager = None
        app.state.playwright_ready = False
        app.state.cache = None

    # Semaphores — total_sem hard-caps ALL contexts; batch_throttle reserves headroom for manual requests
    app.state.total_sem = asyncio.Semaphore(SCRAPE_CONCURRENCY)
    app.state.batch_throttle = asyncio.Semaphore(max(1, SCRAPE_CONCURRENCY - MANUAL_RESERVED))

    app.state.cron_status = {
        "is_running": False,
        "last_run_at": None,
        "last_run_tab": None,
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "total": None,
        "progress": None,
        "error": None,
    }
    app.state.blinkit_cron_status = {
        "is_running": False,
        "last_run_at": None,
        "last_run_tab": None,
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "total": None,
        "progress": None,
        "error": None,
    }
    app.state.flipkart_cron_status = {
        "is_running": False,
        "last_run_at": None,
        "last_run_tab": None,
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "total": None,
        "progress": None,
        "error": None,
    }
    app.state.zepto_cron_status = {
        "is_running": False,
        "last_run_at": None,
        "last_run_tab": None,
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "total": None,
        "progress": None,
        "error": None,
    }
    app.state.instamart_cron_status = {
        "is_running": False,
        "last_run_at": None,
        "last_run_tab": None,
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "total": None,
        "progress": None,
        "error": None,
    }
    app.state.flipkart_minutes_cron_status = {
        "is_running": False,
        "last_run_at": None,
        "last_run_tab": None,
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "total": None,
        "progress": None,
        "error": None,
    }

    app.state.cron_task = None
    app.state.blinkit_cron_task = None
    app.state.flipkart_cron_task = None
    app.state.zepto_cron_task = None
    app.state.instamart_cron_task = None
    app.state.flipkart_minutes_cron_task = None

    app.state.cron_scheduler = setup_scheduler(app)
    if app.state.cron_scheduler:
        logger.info("Cron scheduler active — next run at %02d:%02d IST",
                    int(os.getenv("AMAZON_CRON_HOUR", "10")),
                    int(os.getenv("AMAZON_CRON_MINUTE", "0")))
        logger.info("Cron scheduler active — next run at %02d:%02d IST",
                    int(os.getenv("FLIPKART_CRON_HOUR", "10")),
                    int(os.getenv("FLIPKART_CRON_MINUTE", "0")))
    
    logger.info("Price Checker service ready!")

    yield

    # ── Shutdown ──
    logger.info("Shutting down Price Checker service...")
    if getattr(app.state, "cron_scheduler", None):
        app.state.cron_scheduler.shutdown(wait=False)
        logger.info("Cron scheduler stopped")
    if getattr(app.state, "thread_pool", None):
        app.state.thread_pool.shutdown(wait=False)
        logger.info("Thread pool stopped")
    if getattr(app.state, "browser_manager", None):
        await app.state.browser_manager.close_all()
        logger.info("Playwright browser pool closed")
    if getattr(app.state, "proxy_manager_task", None):
        app.state.proxy_manager_task.cancel()
        
    if playwright_instance:
        try:
            await playwright_instance.stop()
            logger.info("Playwright instance stopped")
        except Exception:
            pass


# ── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Price Checker API",
    description="Scraper-first price checking service for Amazon.in, Flipkart.in, and Blinkit",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://evenflow-pricescraper.vercel.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request logging middleware ──────────────────────────────────────────────

class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return msg.find("/cron-status/all") == -1 and msg.find("/sheets/amazon/api/logs") == -1

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every incoming request: method, path, timestamp."""
    noisy_paths = {"/cron-status/all", "/sheets/amazon/api/logs", "/health"}
    if request.url.path not in noisy_paths:
        timestamp = datetime.now(IST).isoformat()
        logger.info("→ %s %s [%s]", request.method, request.url.path, timestamp)
    response = await call_next(request)
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require a valid JWT on all routes except the public allowlist."""
    if not auth_enabled():
        return await call_next(request)

    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path.rstrip("/") or "/"
    if is_public_route(request.method, path):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    try:
        verify_token(auth_header[7:])
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return await call_next(request)


# ── Global exception handler ───────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return structured JSON error."""
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, str(exc))
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)},
    )


# ── Routes ──────────────────────────────────────────────────────────────────

app.include_router(amazon_price_router)
app.include_router(amazon_sheets_router)
app.include_router(amazon_manual_router)
app.include_router(flipkart_price_router)
app.include_router(flipkart_manual_router)
app.include_router(flipkart_sheets_router)
app.include_router(blinkit_router, prefix="/price", tags=["blinkit"])
app.include_router(zepto_router, prefix="/price", tags=["zepto"])
app.include_router(instamart_router, prefix="/price", tags=["instamart"])
app.include_router(flipkart_minutes_router, prefix="/price", tags=["flipkart_minutes"])


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.post("/auth/login")
async def login(body: LoginRequest):
    """Exchange username/password for a JWT (24h expiry)."""
    if not auth_enabled():
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if not verify_credentials(body.username, body.password):
        await asyncio.sleep(0.5)  # slow down brute-force attempts
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": create_token(body.username), "token_type": "bearer"}


# ── Config endpoint (exposes sheet links to the static frontend) ─────────────

@app.get("/config")
async def get_config():
    """Return public configuration — Google Sheet URLs per platform.
    The frontend fetches this once on load to build 'View Sheet' links.
    """
    def sheet_url(sheet_id: str) -> str | None:
        if not sheet_id:
            return None
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}"

    return {
        "sheets": {
            "amazon":    sheet_url(os.getenv("SPREADSHEET_ID", "")),
            "flipkart":  sheet_url(os.getenv("FLIPKART_SHEET_ID", "")),
            "blinkit":   sheet_url(os.getenv("BLINKIT_SHEET_ID", "")),
            "zepto":     sheet_url(os.getenv("ZEPTO_SHEET_ID", "")),
            "instamart": sheet_url(os.getenv("INSTAMART_SHEET_ID", "")),
            "flipkart_minutes": sheet_url(os.getenv("FLIPKART_MINUTES_SHEET_ID", "")),
        }
    }


@app.get("/cron-status/all")
async def get_all_cron_status(request: Request):
    """Return cron status for all 5 scrapers in a single response."""
    return {
        "amazon": dict(getattr(request.app.state, "cron_status", {})),
        "flipkart": dict(getattr(request.app.state, "flipkart_cron_status", {})),
        "blinkit": dict(getattr(request.app.state, "blinkit_cron_status", {})),
        "zepto": dict(getattr(request.app.state, "zepto_cron_status", {})),
        "instamart": dict(getattr(request.app.state, "instamart_cron_status", {})),
        "flipkart_minutes": dict(getattr(request.app.state, "flipkart_minutes_cron_status", {})),
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Return service status, proxy pool size, and Playwright readiness."""
    proxy_status = app.state.proxy_manager.status()
    return HealthResponse(
        status="ok",
        proxy_pool_size=proxy_status["active"],
        playwright_ready=getattr(app.state, "playwright_ready", False),
        timestamp=datetime.now(IST),
    )


# ── Cross-platform comparison endpoint ──────────────────────────────────────

@app.post("/price/both", response_model=BothResponse, tags=["Price"])
async def check_both_prices(body: BothRequest, request: Request):
    """Scrape both Amazon.in and Flipkart.in in parallel."""
    proxy_manager = request.app.state.proxy_manager

    # Run each scraper sequentially under its own semaphore slot to avoid holding
    # two browser slots simultaneously, which would halve effective concurrency.
    async with sem_with_timeout(request.app.state.total_sem):
        amazon_result = await scrape_amazon(body.asin, get_browser(request.app.state), proxy_manager, skip_curl=True)
    amazon_cookies = amazon_result.pop("_cookies", {}) or {}
    if amazon_cookies:
        curl_data = await fetch_curl_supplement(body.asin, amazon_cookies)
        merge_curl_supplement(amazon_result, curl_data)

    async with sem_with_timeout(request.app.state.total_sem):
        flipkart_result = await scrape_flipkart(body.fsn, get_browser(request.app.state), proxy_manager)

    # Calculate price difference
    price_diff, cheaper_on = _calculate_price_diff(
        amazon_result.get("price", ""),
        flipkart_result.get("price", ""),
    )

    amazon_resp = AmazonResponse(
        asin=amazon_result["asin"],
        price=amazon_result.get("price", ""),
        mrp=amazon_result.get("mrp"),
        rating=amazon_result.get("rating"),
        rating_count=amazon_result.get("rating_count"),
        rating_breakdown=amazon_result.get("rating_breakdown"),
        rank_raw=amazon_result.get("rank_raw"),
        rank_value=amazon_result.get("rank_value"),
        rank_category=amazon_result.get("rank_category"),
        sub_rank_value=amazon_result.get("sub_rank_value"),
        sub_rank_category=amazon_result.get("sub_rank_category"),
        parent_node=amazon_result.get("parent_node"),
        child_node=amazon_result.get("child_node"),
        category_path=amazon_result.get("category_path"),
        status=amazon_result["status"],
        url=amazon_result["url"],
        checked_at=amazon_result["checked_at"],
    )

    flipkart_resp = FlipkartResponse(
        fsn=flipkart_result["fsn"],
        price=flipkart_result.get("price", ""),
        mrp=flipkart_result.get("mrp"),
        discount=flipkart_result.get("discount"),
        rating=flipkart_result.get("rating"),
        rating_count=flipkart_result.get("rating_count"),
        status=flipkart_result["status"],
        url=flipkart_result["url"],
        resolved_url=flipkart_result.get("resolved_url"),
        checked_at=flipkart_result["checked_at"],
    )

    return BothResponse(
        asin=body.asin,
        fsn=body.fsn,
        amazon=amazon_resp,
        flipkart=flipkart_resp,
        price_diff=price_diff,
        cheaper_on=cheaper_on,
    )


def _parse_price_to_float(price_str: str) -> float | None:
    """Extract numeric value from price string like '₹8,999'."""
    if not price_str:
        return None
    cleaned = re.sub(r"[₹,\s]", "", price_str)
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _calculate_price_diff(amazon_price: str, flipkart_price: str) -> tuple[str | None, str | None]:
    """Calculate price difference and determine cheaper platform."""
    a_val = _parse_price_to_float(amazon_price)
    f_val = _parse_price_to_float(flipkart_price)

    if a_val is None or f_val is None:
        return None, None

    diff = abs(a_val - f_val)
    diff_str = f"₹{diff:,.0f}"

    if a_val < f_val:
        return diff_str, "amazon"
    elif f_val < a_val:
        return diff_str, "flipkart"
    else:
        return "₹0", "same"


# ── Static Frontend ──────────────────────────────────────────────────────────

frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "out")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    logger.warning("Frontend build directory '%s' not found. Dashboard will not be served.", frontend_dist)
