"""Zepto price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
import os
from functools import partial

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from zepto.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from zepto.scraper import fetch_zepto_data
from schemas.price import ZeptoRequest, ZeptoAllCitiesRequest, ZeptoResponse
from utils.google_sheets import GoogleSheetsClient

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

    proxy_manager = request.app.state.zepto_proxy_manager

    cache = getattr(request.app.state, "cache", None)
    cache_key = f"zepto_{body.product_id}_{body.city}"
    
    if cache is not None and cache_key in cache:
        result = cache[cache_key]
    else:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            request.app.state.thread_pool,
            partial(
                fetch_zepto_data,
                item_id=body.product_id,
                pincode=city_data["pincode"],
                lat=city_data["lat"],
                lon=city_data["lng"],
                city=body.city,
                store_id=city_data["store_id"],
                proxy_manager=proxy_manager,
            ),
        )
        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result

    return ZeptoResponse(**result)


# ── All cities SSE stream ──────────────────────────────────────────────────

ZEPTO_CONCURRENCY = 5  # Zepto rate-limits aggressively


@router.post("/zepto/all-cities")
async def check_zepto_all_cities(body: ZeptoAllCitiesRequest, request: Request):
    """
    Scrape Zepto for one or more product IDs across all 10 cities.
    Results are streamed as SSE events as they complete.
    """
    proxy_manager = request.app.state.zepto_proxy_manager
    sem = asyncio.Semaphore(ZEPTO_CONCURRENCY)
    queue: asyncio.Queue = asyncio.Queue()

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

    async def worker(product_id: str, loc: dict, fallback_title: str | None = None, fallback_mrp: float | None = None) -> dict:
        cache = getattr(request.app.state, "cache", None)
        cache_key = f"zepto_{product_id}_{loc['name']}"

        if cache is not None and cache_key in cache:
            return cache[cache_key].copy()

        async with sem:
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(
                    request.app.state.thread_pool,
                    partial(
                        fetch_zepto_data,
                        item_id=product_id,
                        pincode=loc["pincode"],
                        lat=loc["lat"],
                        lon=loc["lng"],
                        city=loc["name"],
                        store_id=loc["store_id"],
                        proxy_manager=proxy_manager,
                        fallback_title=fallback_title,
                        fallback_mrp=fallback_mrp,
                    ),
                )
            except Exception:
                logger.exception("zepto worker error for %s %s", product_id, loc["name"])
                return {"product_id": product_id, "city": loc["name"], "status": "error"}

            if cache is not None and result.get("status") not in ("error", "invalid_format"):
                cache[cache_key] = result.copy()

            return result

    async def event_stream():
        done = 0

        # 1. First-city pre-check: Scrape LOCATIONS[0] for all PIDs concurrently
        precheck_tasks = []
        for pid in body.product_ids:
            if LOCATIONS:
                precheck_tasks.append(asyncio.create_task(worker(pid.strip(), LOCATIONS[0])))
                
        # Wait for all prechecks and store their titles
        first_city_results = {}
        for coro in asyncio.as_completed(precheck_tasks):
            result = await coro
            pid = result["product_id"]
            first_city_results[pid] = result
            done += 1
            yield f"data: {json.dumps({**result, 'progress': done, 'total': total})}\n\n"

        # 2. Scrape remaining cities, injecting fallback title/mrp if available
        remaining_tasks = []
        for pid in body.product_ids:
            pid = pid.strip()
            fallback_title = first_city_results.get(pid, {}).get("title")
            fallback_mrp = first_city_results.get(pid, {}).get("mrp")
            if fallback_title == "Not Found" or fallback_title == "Unknown Product":
                fallback_title = None

            for loc in LOCATIONS[1:]:
                remaining_tasks.append(asyncio.create_task(worker(pid, loc, fallback_title, fallback_mrp)))

        for coro in asyncio.as_completed(remaining_tasks):
            result = await coro
            done += 1
            yield f"data: {json.dumps({**result, 'progress': done, 'total': total})}\n\n"

        yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
