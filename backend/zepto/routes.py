"""Zepto price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
import os

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from zepto.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from zepto.browser_scraper import scrape_one
from schemas.price import ZeptoRequest, ZeptoAllCitiesRequest, ZeptoResponse
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import batch_context, sem_with_timeout

logger = logging.getLogger(__name__)

router = APIRouter(tags=["zepto"])


# ── Single city lookup ──────────────────────────────────────────────────────

@router.post("/zepto", response_model=ZeptoResponse)
async def check_zepto_price(body: ZeptoRequest, request: Request):
    """Scrape Zepto for a single product in a single city."""
    city_data = LOCATIONS_BY_CITY.get(body.city)
    if not city_data:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid city '{body.city}'. Valid cities: {CITY_NAMES}",
        )

    cache = getattr(request.app.state, "cache", None)
    cache_key = f"zepto_{body.product_id}_{body.city}"

    if cache is not None and cache_key in cache:
        result = cache[cache_key]
    else:
        browser = await request.app.state.browser_manager.acquire() if getattr(request.app.state, "browser_manager", None) else None
        if not browser:
            raise HTTPException(status_code=503, detail="Browser pool unavailable")
        async with sem_with_timeout(request.app.state.total_sem):
            result = await scrape_one(browser, city_data, body.product_id)
        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result

    return ZeptoResponse(**result)


# ── All cities SSE stream ──────────────────────────────────────────────────


@router.post("/zepto/all-cities")
async def check_zepto_all_cities(body: ZeptoAllCitiesRequest, request: Request):
    """
    Scrape Zepto for one or more product IDs across all 10 cities.
    Results are streamed as SSE events as they complete.
    """
    # Build work items: (product_id, city_data)
    work_items = []
    for pid in body.product_ids:
        for loc in LOCATIONS:
            work_items.append((pid.strip(), loc))

    total = len(work_items)

    if total == 0:
        async def empty_stream():
            yield f"data: {json.dumps({'done': True, 'total': 0})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    async def worker(product_id: str, loc: dict) -> dict:
        cache = getattr(request.app.state, "cache", None)
        cache_key = f"zepto_{product_id}_{loc['name']}"

        if cache is not None and cache_key in cache:
            return cache[cache_key].copy()

        browser = await request.app.state.browser_manager.acquire() if getattr(request.app.state, "browser_manager", None) else None
        if not browser:
            return {"product_id": product_id, "city": loc["name"], "status": "error",
                    "error_message": "browser pool unavailable", "price": None, "mrp": None,
                    "title": None, "is_sold_out": False, "url": None, "checked_at": None}

        async with batch_context(request.app.state):
            result = await scrape_one(browser, loc, product_id)

        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result.copy()

        return result

    async def event_stream():
        done = 0
        tasks = [
            asyncio.create_task(worker(pid.strip(), loc))
            for pid in body.product_ids
            for loc in LOCATIONS
        ]
        try:
            for coro in asyncio.as_completed(tasks):
                result = await coro
                done += 1
                yield f"data: {json.dumps({**result, 'progress': done, 'total': total})}\n\n"

            yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


# ── Sheet-based manual trigger ──────────────────────────────────────────────

@router.post("/zepto/api/trigger-manual-scheduler")
async def trigger_manual_zepto(request: Request):
    """Trigger a full Zepto scrape of all PIDs from the sheet (runs in background)."""
    if request.app.state.zepto_cron_status.get("is_running"):
        raise HTTPException(status_code=409, detail="A Zepto scrape run is already in progress")
    from scheduler import run_manual_zepto_trigger
    task = asyncio.create_task(run_manual_zepto_trigger(request.app))
    request.app.state.zepto_cron_task = task
    return {"status": "started"}


@router.post("/zepto/api/cancel-manual-scheduler")
async def cancel_manual_zepto(request: Request):
    """Cancel a running Zepto manual scrape."""
    task = request.app.state.zepto_cron_task
    if task and not task.done():
        task.cancel()
        return {"status": "cancelling"}
    raise HTTPException(status_code=409, detail="No running Zepto scrape to cancel")


@router.get("/zepto/cron-status")
async def zepto_cron_status(request: Request):
    """Return current Zepto scrape status."""
    return dict(getattr(request.app.state, "zepto_cron_status", {}))


@router.get("/zepto/products")
async def get_zepto_products():
    """Return product catalog (id, title, brand) from the Zepto source sheet."""
    sheet_id = os.getenv("ZEPTO_SHEET_ID", "")
    source_tab = os.getenv("ZEPTO_SOURCE_TAB", "Sheet1")
    if not sheet_id:
        raise HTTPException(status_code=503, detail="Zepto sheet not configured (set ZEPTO_SHEET_ID)")
    try:
        return GoogleSheetsClient().get_products_from_sheet(sheet_id, source_tab)
    except Exception as e:
        logger.exception("Failed to fetch Zepto products")
        raise HTTPException(status_code=500, detail=str(e))
