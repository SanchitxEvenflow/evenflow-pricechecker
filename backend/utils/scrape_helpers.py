"""Shared scraping constants and helpers used by both routes/sheets.py and scheduler.py."""

# 3 concurrent Playwright sessions per proxy — raise to 40 if proxies hold, lower if blocks increase
SCRAPE_CONCURRENCY = 30
CHUNK_SIZE = 50

# Canonical city order — must match blinkit/locations.py LOCATIONS list
BLINKIT_CITIES = [
    "Bangalore", "NCR", "Mumbai", "Hyderabad", "Kolkata",
    "Pune", "Ahmedabad", "Chennai", "Patna", "Dehradun",
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
        status = r.get("status", "")
        values.extend([
            str(price) if price is not None else "",
            str(mrp) if mrp is not None else "",
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
    """Format a Flipkart scrape result into a sheet update dict (7 columns B–H)."""
    return {
        "row": res["row"],
        "values": [
            res.get("price", ""),
            res.get("mrp", ""),
            res.get("discount", ""),
            res.get("rating", ""),
            res.get("rating_count", ""),
            res.get("status", "unknown"),
            res.get("checked_at", ""),
        ],
    }

