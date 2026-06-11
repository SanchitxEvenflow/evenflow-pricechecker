"""instamart price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from instamart.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from instamart.scraper import fetch_instamart_data
from schemas.price import InstamartRequest, InstamartAllCitiesRequest, InstamartResponse
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import batch_context, get_browser, sem_with_timeout

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

    proxy_manager = request.app.state.proxy_manager

    async with sem_with_timeout(request.app.state.total_sem):
        result = await fetch_instamart_data(
            item_id=body.product_id,
            lat=city_data["lat"],
            lon=city_data["lng"],
            city=body.city,
            store_id=city_data["store_id"],
            browser=get_browser(request.app.state),
            proxy_manager=proxy_manager,
        )

    return InstamartResponse(**result)


# ── All cities SSE stream ──────────────────────────────────────────────────

@router.post("/instamart/all-cities")
async def check_instamart_all_cities(body: InstamartAllCitiesRequest, request: Request):
    """
    Scrape instamart for one or more product IDs across all cities.
    Results are streamed as SSE events as they complete.
    """
    proxy_manager = request.app.state.proxy_manager
    queue: asyncio.Queue = asyncio.Queue()
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

    async def worker(product_id: str, loc: dict) -> None:
        async with batch_context(app_state):
            result = await fetch_instamart_data(
                item_id=product_id,
                lat=loc["lat"],
                lon=loc["lng"],
                city=loc["name"],
                store_id=loc["store_id"],
                browser=get_browser(app_state),
                proxy_manager=proxy_manager,
            )
            await queue.put(result)

    async def event_stream():
        tasks = [asyncio.create_task(worker(pid, loc)) for pid, loc in work_items]
        done = 0
        try:
            while done < total:
                result = await queue.get()
                done += 1
                payload = json.dumps({
                    **result,
                    "progress": done,
                    "total": total,
                })
                yield f"data: {payload}\n\n"

            await asyncio.gather(*tasks, return_exceptions=True)
            yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Sheet-based manual trigger ──────────────────────────────────────────────

@router.post("/instamart/api/trigger-manual-scheduler")
async def trigger_manual_instamart(request: Request):
    """Trigger a full instamart scrape of all PIDs from the sheet (runs in background)."""
    if request.app.state.instamart_cron_status.get("is_running"):
        raise HTTPException(status_code=409, detail="An instamart scrape run is already in progress")
    from scheduler import run_manual_instamart_trigger
    asyncio.create_task(run_manual_instamart_trigger(request.app))
    return {"status": "started"}


@router.get("/instamart/cron-status")
async def instamart_cron_status(request: Request):
    """Return current instamart scrape status."""
    return dict(getattr(request.app.state, "instamart_cron_status", {}))


@router.get("/instamart/products")
async def get_instamart_products():
    """Return product catalog (id, title, brand) from the Instamart source sheet."""
    sheet_id = os.getenv("INSTAMART_SHEET_ID", "")
    source_tab = os.getenv("INSTAMART_SOURCE_TAB", "Sheet1")
    if not sheet_id:
        raise HTTPException(status_code=503, detail="Instamart sheet not configured (set INSTAMART_SHEET_ID)")
    try:
        return GoogleSheetsClient().get_products_from_sheet(sheet_id, source_tab)
    except Exception as e:
        logger.exception("Failed to fetch Instamart products")
        raise HTTPException(status_code=500, detail=str(e))
