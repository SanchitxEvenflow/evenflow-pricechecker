"""instamart price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
import os

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from instamart.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from instamart.browser_scraper import scrape_one
from schemas.price import InstamartRequest, InstamartAllCitiesRequest, InstamartResponse
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import batch_context, sem_with_timeout

logger = logging.getLogger(__name__)

router = APIRouter(tags=["instamart"])


# ── Single city lookup ──────────────────────────────────────────────────────

@router.post("/instamart", response_model=InstamartResponse)
async def check_instamart_price(body: InstamartRequest, request: Request):
    """Scrape instamart for a single product in a single city."""
    city_data = LOCATIONS_BY_CITY.get(body.city)
    if not city_data:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid city '{body.city}'. Valid cities: {CITY_NAMES}",
        )

    cache = getattr(request.app.state, "cache", None)
    cache_key = f"instamart_{body.product_id}_{body.city}"

    if cache is not None and cache_key in cache:
        result = cache[cache_key]
    else:
        browser = await request.app.state.browser_manager.acquire() if getattr(request.app.state, "browser_manager", None) else None
        if not browser:
            raise HTTPException(status_code=503, detail="Browser pool unavailable")
        _pool = getattr(request.app.state, "instamart_proxy_pool", None)
        _proxy = _pool.pick() if _pool else None
        async with sem_with_timeout(request.app.state.total_sem):
            result = await scrape_one(browser, city_data, body.product_id, proxy=_proxy)
        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result

    return InstamartResponse(**result)


# ── All cities SSE stream ──────────────────────────────────────────────────

@router.post("/instamart/all-cities")
async def check_instamart_all_cities(body: InstamartAllCitiesRequest, request: Request):
    """
    Scrape instamart for one or more product IDs across all cities.
    Results are streamed as SSE events as they complete.
    """
    app_state = request.app.state

    # Build work items: (product_id, city_data)
    work_items = [
        (pid.strip(), loc)
        for pid in body.product_ids
        for loc in LOCATIONS
    ]
    total = len(work_items)

    if total == 0:
        async def empty_stream():
            yield f"data: {json.dumps({'done': True, 'total': 0})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    async def worker(product_id: str, loc: dict, target_variant_name: str | None = None) -> dict:
        is_duplicate = sum(1 for l in LOCATIONS if l["name"] == loc["name"]) > 1
        display_city = f"{loc['name']} - {loc['area']}" if is_duplicate else loc["name"]
        
        cache = getattr(request.app.state, "cache", None)
        cache_key = f"instamart_{product_id}_{display_city}"
        
        if cache is not None and cache_key in cache:
            return cache[cache_key].copy()

        browser = await app_state.browser_manager.acquire() if getattr(app_state, "browser_manager", None) else None
        if not browser:
            return {"product_id": product_id, "city": display_city, "status": "error",
                    "error_message": "browser pool unavailable", "price": None, "mrp": None,
                    "title": None, "is_sold_out": False, "url": None, "checked_at": None}

        # Report under display_city (disambiguates duplicate city names).
        loc_display = {**loc, "name": display_city}
        _pool = getattr(app_state, "instamart_proxy_pool", None)
        _proxy = _pool.pick() if _pool else None
        async with batch_context(app_state):
            result = await scrape_one(browser, loc_display, product_id, target_variant_name, proxy=_proxy)

        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result.copy()

        return result

    async def event_stream():
        done = 0
        precheck_tasks = []
        remaining_tasks = []
        try:
            # 1. First-city pre-check: Scrape LOCATIONS[0] for all PIDs concurrently
            for pid in body.product_ids:
                if LOCATIONS:
                    precheck_tasks.append(asyncio.create_task(worker(pid.strip(), LOCATIONS[0])))
                    
            # Wait for all prechecks and yield them
            target_variants = {}
            for coro in asyncio.as_completed(precheck_tasks):
                result = await coro
                target_variants[result['product_id']] = result.get('title')
                done += 1
                yield f"data: {json.dumps({**result, 'progress': done, 'total': total})}\n\n"

            # 2. Scrape remaining cities
            for pid in body.product_ids:
                clean_pid = pid.strip()
                target_variant = target_variants.get(clean_pid)
                for loc in LOCATIONS[1:]:
                    remaining_tasks.append(asyncio.create_task(worker(clean_pid, loc, target_variant)))

            for coro in asyncio.as_completed(remaining_tasks):
                result = await coro
                done += 1
                yield f"data: {json.dumps({**result, 'progress': done, 'total': total})}\n\n"

            yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"
        finally:
            for task in precheck_tasks + remaining_tasks:
                if not task.done():
                    task.cancel()

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


# ── Sheet-based manual trigger ──────────────────────────────────────────────

@router.post("/instamart/api/trigger-manual-scheduler")
async def trigger_manual_instamart(request: Request):
    """Trigger a full instamart scrape of all PIDs from the sheet (runs in background)."""
    if request.app.state.instamart_cron_status.get("is_running"):
        raise HTTPException(status_code=409, detail="An instamart scrape run is already in progress")
    from scheduler import run_manual_instamart_trigger
    task = asyncio.create_task(run_manual_instamart_trigger(request.app))
    request.app.state.instamart_cron_task = task
    return {"status": "started"}


@router.post("/instamart/api/cancel-manual-scheduler")
async def cancel_manual_instamart(request: Request):
    """Cancel a running Instamart manual scrape."""
    task = request.app.state.instamart_cron_task
    if task and not task.done():
        task.cancel()
        return {"status": "cancelling"}
    raise HTTPException(status_code=409, detail="No running Instamart scrape to cancel")


@router.get("/instamart/cron-status")
async def instamart_cron_status(request: Request):
    """Return current instamart scrape status."""
    return dict(getattr(request.app.state, "instamart_cron_status", {}))


@router.get("/instamart/products")
async def get_instamart_products():
    """Return product catalog (id, title) from the Instamart source sheet."""
    sheet_id = os.getenv("INSTAMART_SHEET_ID", "")
    source_tab = os.getenv("INSTAMART_SOURCE_TAB", "Sheet1")
    if not sheet_id:
        raise HTTPException(status_code=503, detail="Instamart sheet not configured (set INSTAMART_SHEET_ID)")
    try:
        return GoogleSheetsClient().get_products_from_sheet(sheet_id, source_tab)
    except Exception as e:
        logger.exception("Failed to fetch Instamart products")
        raise HTTPException(status_code=500, detail=str(e))
