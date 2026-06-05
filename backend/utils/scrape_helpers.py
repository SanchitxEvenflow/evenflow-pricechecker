"""Shared scraping constants and helpers used by both routes/sheets.py and scheduler.py."""

import os

# Concurrency limit: tune based on available RAM (150MB per Playwright browser)
# Default: 5 (safe for 2GB RAM). Raise to 10-15 if OOM doesn't occur, lower if it does.
SCRAPE_CONCURRENCY = int(os.getenv("SCRAPE_CONCURRENCY", "5"))
SHEETS_BATCH_SIZE = 100  # Google Sheets API batch limit
SHEET_HEADER_ROWS = 1  # Number of header rows in sheets
CHUNK_SIZE = 50

# Canonical city order — must match blinkit/locations.py LOCATIONS list
BLINKIT_CITIES = [
    "Bangalore", "NCR", "Mumbai", "Hyderabad", "Kolkata",
    "Pune", "Ahmedabad", "Chennai", "Patna", "Dehradun",
]

ZEPTO_CITIES = [
    "Bangalore", "NCR", "Mumbai", "Hyderabad", "Kolkata",
    "Pune", "Ahmedabad", "Chennai", "Dehradun",
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

