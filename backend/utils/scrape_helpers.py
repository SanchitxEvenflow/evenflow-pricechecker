"""Shared scraping constants and helpers used by both routes/sheets.py and scheduler.py."""

# 3 concurrent Playwright sessions per proxy — raise to 40 if proxies hold, lower if blocks increase
SCRAPE_CONCURRENCY = 30
CHUNK_SIZE = 50


def format_breakdown(breakdown: dict | None) -> str:
    if not breakdown:
        return ""
    parts = []
    for star in ("5_star", "4_star", "3_star", "2_star", "1_star"):
        val = breakdown.get(star)
        if val:
            parts.append(f"{star[0]}★:{val}")
    return " ".join(parts)


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
