"""Manual ASIN scraping — no Google Sheets involved. Results streamed via SSE."""

import asyncio
import json
import logging
import re
from typing import List

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from scrapers.amazon import scrape_amazon
from utils.scrape_helpers import SCRAPE_CONCURRENCY

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Manual"])


class ManualScrapeRequest(BaseModel):
    asins: List[str]


def _validate_asin(asin: str) -> bool:
    """ASIN must be exactly 10 alphanumeric characters."""
    return bool(re.match(r"^[A-Z0-9]{10}$", asin.strip().upper()))


@router.post("/scrape-manual")
async def scrape_manual(body: ManualScrapeRequest, request: Request):
    """Scrape a list of ASINs manually. Results are streamed via SSE — no sheet writes."""
    browser = request.app.state.playwright_browser
    proxy_manager = request.app.state.proxy_manager

    if not browser:
        raise HTTPException(status_code=503, detail="Playwright browser not available")

    # Clean, deduplicate, validate
    raw_asins = [a.strip().upper() for a in body.asins if a.strip()]
    seen = set()
    clean_asins = []
    invalid_asins = []

    for asin in raw_asins:
        if asin in seen:
            continue
        seen.add(asin)
        if _validate_asin(asin):
            clean_asins.append(asin)
        else:
            invalid_asins.append(asin)

    if not clean_asins and not invalid_asins:
        raise HTTPException(status_code=400, detail="No ASINs provided")

    total = len(clean_asins) + len(invalid_asins)
    sem = asyncio.Semaphore(SCRAPE_CONCURRENCY)
    queue: asyncio.Queue = asyncio.Queue()

    # Push invalid ASINs as immediate errors
    for asin in invalid_asins:
        await queue.put({
            "asin": asin,
            "price": "",
            "rating": None,
            "rating_count": None,
            "status": "invalid_format",
            "url": "",
            "checked_at": "",
        })

    async def worker(asin: str) -> None:
        async with sem:
            result = await scrape_amazon(asin, browser, proxy_manager)
            await queue.put(result)

    async def event_stream():
        tasks = [asyncio.create_task(worker(a)) for a in clean_asins]
        done = len(invalid_asins)  # invalid ones are already queued

        # Yield invalid results immediately
        for _ in range(len(invalid_asins)):
            result = await queue.get()
            done_count = _ + 1
            payload = json.dumps({**result, "progress": done_count, "total": total})
            yield f"data: {payload}\n\n"

        # Yield scraped results as they complete
        scraped_done = 0
        while scraped_done < len(clean_asins):
            result = await queue.get()
            scraped_done += 1
            progress = len(invalid_asins) + scraped_done
            payload = json.dumps({**result, "progress": progress, "total": total})
            yield f"data: {payload}\n\n"

        await asyncio.gather(*tasks, return_exceptions=True)
        yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
