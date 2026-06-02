"""Shared scraping constants and helpers used by both routes/sheets.py and scheduler.py."""

# 3 concurrent Playwright sessions per proxy — raise to 40 if proxies hold, lower if blocks increase
SCRAPE_CONCURRENCY = 30
CHUNK_SIZE = 50


def format_update(res: dict) -> dict:
    return {
        "row": res["row"],
        "values": [
            res.get("price", ""),
            res.get("rating", ""),
            res.get("rating_count", ""),
            res.get("parent_node", ""),
            res.get("child_node", ""),
            res.get("status", "unknown"),
            res.get("checked_at", ""),
        ],
    }
