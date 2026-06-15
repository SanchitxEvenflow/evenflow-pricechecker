"""Shared scraping constants and helpers used by both routes/sheets.py and scheduler.py."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Concurrency limit: tune based on available RAM (150MB per Playwright browser)
# Default: 5 (safe for 2GB RAM). Raise to 10-15 if OOM doesn't occur, lower if it does.
SCRAPE_CONCURRENCY = int(os.getenv("SCRAPE_CONCURRENCY", "5"))
# Slots reserved for manual (single-product) requests even during batch runs.
MANUAL_RESERVED = int(os.getenv("MANUAL_RESERVED", "2"))
# Number of Chromium browser instances to launch at startup.
BROWSER_POOL_SIZE = int(os.getenv("BROWSER_POOL_SIZE", "2"))
# Seconds to wait for a semaphore slot before returning 503.
SCRAPE_TIMEOUT = float(os.getenv("SCRAPE_TIMEOUT", "60"))

SHEETS_BATCH_SIZE = 100  # Google Sheets API batch limit
SHEET_HEADER_ROWS = 1  # Number of header rows in sheets
CHUNK_SIZE = 50


def get_browser(app_state):
    """Round-robin browser from pool. itertools.cycle.next() is atomic in CPython."""
    browser = next(app_state.browser_cycle)
    logger.debug("Browser picked: %d", id(browser))
    return browser


@asynccontextmanager
async def sem_with_timeout(sem: asyncio.Semaphore, timeout: float = SCRAPE_TIMEOUT):
    """Acquire semaphore slot or raise HTTP 503 after timeout seconds."""
    acquired = False
    try:
        await asyncio.wait_for(sem.acquire(), timeout=timeout)
        acquired = True
        yield
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail="Service busy — too many concurrent scrapes. Retry shortly.",
        )
    finally:
        if acquired:
            sem.release()


@asynccontextmanager
async def batch_context(app_state):
    """Acquire batch_throttle then total_sem for batch workers.

    Guarantees batch slots ≤ (SCRAPE_CONCURRENCY - MANUAL_RESERVED) and
    total Playwright contexts ≤ SCRAPE_CONCURRENCY at all times.
    Order: batch_throttle first, then total_sem — consistent order prevents deadlock.
    """
    async with app_state.batch_throttle:
        async with app_state.total_sem:
            yield

# Canonical city order — must match blinkit/locations.py LOCATIONS list
BLINKIT_CITIES = [
    "Bangalore", "NCR", "Mumbai", "Hyderabad", "Kolkata",
    "Pune", "Ahmedabad", "Chennai", "Patna", "Dehradun",
]

ZEPTO_CITIES = [
    "Bangalore", "NCR", "Mumbai", "Hyderabad", "Kolkata",
    "Pune", "Ahmedabad", "Chennai", "Dehradun",
]

# Canonical city order — must match instamart/locations.py coverage.
INSTAMART_CITIES = [
    "Bangalore", "NCR", "Mumbai", "Hyderabad", "Kolkata",
    "Pune", "Ahmedabad", "Chennai",
]


def format_breakdown(breakdown: dict | None) -> str:
    if not breakdown:
        return ""

    parts = []
    for star in ("5_star", "4_star", "3_star", "2_star", "1_star"):
        val = breakdown.get(star)
        if val:
            parts.append(f"{star[0]}★:{val}")
    return " ".join(parts)


def format_blinkit_row(results_by_city: dict) -> list:
    """Flatten per-city Blinkit results into a single sheet row.

    Returns a list of 30 values: [price, mrp, status] × 10 cities in BLINKIT_CITIES order.
    """
    values = []
    for city in BLINKIT_CITIES:
        r = results_by_city.get(city, {})
        price = r.get("price")
        mrp = r.get("mrp")
        status = r.get("status") or ""
        values.extend([
            f"{price:.2f}" if price is not None else "",
            f"{mrp:.2f}" if mrp is not None else "",
            status,
        ])
    return values


def format_zepto_row(results_by_city: dict) -> list:
    """Flatten per-city Zepto results into a single sheet row.

    Returns a list of 27 values: [price, mrp, status] × 9 cities in ZEPTO_CITIES order.
    """
    values = []
    for city in ZEPTO_CITIES:
        r = results_by_city.get(city, {})
        price = r.get("price")
        mrp = r.get("mrp")
        status = r.get("status") or ""
        values.extend([
            f"{price:.2f}" if price is not None else "",
            f"{mrp:.2f}" if mrp is not None else "",
            status,
        ])
    return values


def format_update(res: dict) -> dict:
    return {
        "row": res["row"],
        "values": [
            res.get("price", ""),
            res.get("rating", ""),
            res.get("rating_count", ""),
            format_breakdown(res.get("rating_breakdown")),
            res.get("parent_node", ""),
            res.get("rank_value", ""),
            res.get("child_node", ""),
            res.get("sub_rank_value", ""),
            res.get("status", "unknown"),
            res.get("checked_at", ""),
        ],
    }


def format_flipkart_update(res: dict) -> dict:
    """Format a Flipkart scrape result into a sheet update dict (8 columns B–I)."""
    return {
        "row": res["row"],
        "values": [
            res.get("price", ""),
            res.get("mrp", ""),
            res.get("discount", ""),
            res.get("rating", ""),
            res.get("rating_count", ""),
            res.get("fulfilled_by", ""),
            res.get("status", "unknown"),
            res.get("checked_at", ""),
        ],
    }


def format_instamart_row(results_by_city: dict) -> list:
    """Flatten per-city Instamart results into a single sheet row.

    Returns a list of 30 values: [price, mrp, status] × 10 cities in INSTAMART_CITIES order.

    Expected city result shape:
      {
        "price": float|None,
        "mrp": float|None,
        "status": str
      }
    """
    values: list[str] = []
    for city in INSTAMART_CITIES:
        r = results_by_city.get(city, {})
        price = r.get("price")
        mrp = r.get("mrp")
        status = r.get("status") or ""
        values.extend([
            f"{price:.2f}" if price is not None else "",
            f"{mrp:.2f}" if mrp is not None else "",
            status,
        ])
    return values


