"""flipkart minutes price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from flipkart_minutes.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from flipkart_minutes.scraper import fetch_flipkart_minutes_data
from schemas.price import FlipkartMinutesRequest, FlipkartMinutesAllCitiesRequest, FlipkartMinutesResponse
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import batch_context, sem_with_timeout

logger = logging.getLogger(__name__)

router = APIRouter(tags=["flipkart_minutes"])


# ── Single city lookup ──────────────────────────────────────────────────────

@router.post("/flipkart-minutes", response_model=FlipkartMinutesResponse)
async def check_flipkart_minutes_price(body: FlipkartMinutesRequest, request: Request):
    """Scrape flipkart minutes for a single product in a single city."""
    city_data = LOCATIONS_BY_CITY.get(body.city)
    if not city_data:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid city '{body.city}'. Valid cities: {CITY_NAMES}",
        )

    cache = getattr(request.app.state, "cache", None)
    cache_key = f"flipkart_minutes_{body.product_id}_{body.city}"
    
    if cache is not None and cache_key in cache:
        result = cache[cache_key]
    else:
        async with sem_with_timeout(request.app.state.total_sem):
            try:
                result = await fetch_flipkart_minutes_data(
                    pid=body.product_id,
                    city=body.city,
                    app_state=request.app.state,
                )
            except RuntimeError as e:
                raise HTTPException(status_code=503, detail=str(e))
        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result

    return FlipkartMinutesResponse(**result)


# ── All cities SSE stream ──────────────────────────────────────────────────

@router.post("/flipkart-minutes/all-cities")
async def check_flipkart_minutes_all_cities(body: FlipkartMinutesAllCitiesRequest, request: Request):
    """
    Scrape flipkart minutes for one or more product IDs across all cities.
    Results are streamed as SSE events as they complete.
    """
    app_state = request.app.state

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

    async def worker(product_id: str, loc: dict) -> dict:
        is_duplicate = sum(1 for l in LOCATIONS if l["name"] == loc["name"]) > 1
        display_city = f"{loc['name']} - {loc['area']}" if is_duplicate else loc["name"]
        
        cache = getattr(request.app.state, "cache", None)
        cache_key = f"flipkart_minutes_{product_id}_{display_city}"
        
        if cache is not None and cache_key in cache:
            return cache[cache_key].copy()

        async with batch_context(app_state):
            try:
                result = await fetch_flipkart_minutes_data(
                    pid=product_id,
                    city=display_city,
                    app_state=app_state,
                )
            except Exception as e:
                logger.error("[FlipkartMinutes] worker error for %s %s: %s", product_id, display_city, e)
                return {"product_id": product_id, "city": display_city, "status": "error", "error_message": str(e)}

            if cache is not None and result.get("status") not in ("error", "invalid_format"):
                cache[cache_key] = result.copy()

            return result

    async def event_stream():
        done = 0
        tasks = []
        try:
            for pid in body.product_ids:
                clean_pid = pid.strip()
                for loc in LOCATIONS:
                    tasks.append(asyncio.create_task(worker(clean_pid, loc)))

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

@router.post("/flipkart-minutes/api/trigger-manual-scheduler")
async def trigger_manual_flipkart_minutes(request: Request):
    """Trigger a full flipkart minutes scrape of all PIDs from the sheet."""
    if getattr(request.app.state, "flipkart_minutes_cron_status", {}).get("is_running"):
        raise HTTPException(status_code=409, detail="A flipkart minutes scrape run is already in progress")
    from scheduler import run_manual_flipkart_minutes_trigger
    task = asyncio.create_task(run_manual_flipkart_minutes_trigger(request.app))
    request.app.state.flipkart_minutes_cron_task = task
    return {"status": "started"}


@router.post("/flipkart-minutes/api/cancel-manual-scheduler")
async def cancel_manual_flipkart_minutes(request: Request):
    """Cancel a running Flipkart Minutes manual scrape."""
    task = getattr(request.app.state, "flipkart_minutes_cron_task", None)
    if task and not task.done():
        task.cancel()
        return {"status": "cancelling"}
    raise HTTPException(status_code=409, detail="No running Flipkart Minutes scrape to cancel")


@router.get("/flipkart-minutes/cron-status")
async def flipkart_minutes_cron_status(request: Request):
    """Return current flipkart minutes scrape status."""
    return dict(getattr(request.app.state, "flipkart_minutes_cron_status", {}))


@router.get("/flipkart-minutes/products")
@router.get("/flipkart_minutes/products")
async def get_flipkart_minutes_products():
    """Return product catalog (id, title) from the Flipkart Minutes source sheet."""
    sheet_id = os.getenv("FLIPKART_MINUTES_SHEET_ID", "")
    source_tab = os.getenv("FLIPKART_MINUTES_SOURCE_TAB", "Sheet1")
    if not sheet_id:
        raise HTTPException(status_code=503, detail="Flipkart Minutes sheet not configured (set FLIPKART_MINUTES_SHEET_ID)")
    try:
        return GoogleSheetsClient().get_products_from_sheet(sheet_id, source_tab)
    except Exception as e:
        logger.exception("Failed to fetch Flipkart Minutes products")
        raise HTTPException(status_code=500, detail=str(e))
