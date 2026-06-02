"""
FastAPI Price Checker — Amazon.in & Flipkart.in scraper service.

No database, no auth — pure request → scrape → return JSON.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from proxy.manager import ProxyManager
from routes.price import router as price_router
from routes.sheets import router as sheets_router
from schemas.price import HealthResponse

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
    """Startup: init ProxyManager + launch Playwright browser. Shutdown: close browser."""
    # ── Startup ──
    logger.info("Starting Price Checker service...")

    # Initialize proxy manager
    proxy_file = os.getenv("PROXY_FILE", "proxies.txt")
    app.state.proxy_manager = ProxyManager(proxy_file)
    proxy_status = app.state.proxy_manager.status()
    logger.info("Proxy pool: %d active, %d dead", proxy_status["active"], proxy_status["dead"])

    # Launch Playwright browser
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
    playwright_instance = None
    browser = None

    try:
        from playwright.async_api import async_playwright

        playwright_instance = await async_playwright().start()
        browser = await playwright_instance.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
            ],
        )
        app.state.playwright_instance = playwright_instance
        app.state.playwright_browser = browser
        app.state.playwright_ready = True
        logger.info("Playwright Chromium browser launched (headless=%s)", headless)

    except Exception as e:
        logger.error("Failed to launch Playwright browser: %s", str(e))
        app.state.playwright_instance = None
        app.state.playwright_browser = None
        app.state.playwright_ready = False

    logger.info("Price Checker service ready!")

    yield

    # ── Shutdown ──
    logger.info("Shutting down Price Checker service...")
    if browser:
        try:
            await browser.close()
            logger.info("Playwright browser closed")
        except Exception:
            pass
    if playwright_instance:
        try:
            await playwright_instance.stop()
            logger.info("Playwright instance stopped")
        except Exception:
            pass


# ── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Price Checker API",
    description="Scraper-first price checking service for Amazon.in and Flipkart.in",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request logging middleware ──────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every incoming request: method, path, timestamp."""
    timestamp = datetime.now(IST).isoformat()
    logger.info("→ %s %s [%s]", request.method, request.url.path, timestamp)
    response = await call_next(request)
    return response


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

app.include_router(price_router)
app.include_router(sheets_router)


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


# ── Static Frontend ──────────────────────────────────────────────────────────

frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "out")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    logger.warning("Frontend build directory '%s' not found. Dashboard will not be served.", frontend_dist)
