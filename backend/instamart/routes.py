"""instamart price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
from functools import partial

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from instamart.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from instamart.scraper import fetch_instamart_data
from schemas.price import instamartRequest, instamartAllCitiesRequest, instamartResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["instamart"])


# ── Single city lookup ──────────────────────────────────────────────────────

@router.post("/instamart", response_model=instamartResponse)
async def check_instamart_price(body: instamartRequest, request: Request):
    """Scrape instamart for a single product in a single city."""
    city_data = LOCATIONS_BY_CITY.get(body.city)
    if not city_data:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid city '{body.city}'. Valid cities: {CITY_NAMES}",
        )

    proxy_manager = request.app.state.proxy_manager

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        partial(
            fetch_instamart_data,
            item_id=body.product_id,
            pincode=city_data["pincode"],
            lat=city_data["lat"],
            lon=city_data["lng"],
            city=body.city,
            store_id=city_data["store_id"],
            proxy_manager=proxy_manager,
        ),
    )

    return instamartResponse(**result)


# ── All cities SSE stream ──────────────────────────────────────────────────

instamart_CONCURRENCY = 5  # instamart rate-limits aggressively


@router.post("/instamart/all-cities")
async def check_instamart_all_cities(body: instamartAllCitiesRequest, request: Request):
    """
    Scrape instamart for one or more product IDs across all 10 cities.
    Results are streamed as SSE events as they complete.
    """
    proxy_manager = request.app.state.proxy_manager
    sem = asyncio.Semaphore(instamart_CONCURRENCY)
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

    async def worker(product_id: str, loc: dict) -> None:
        async with sem:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                partial(
                    fetch_instamart_data,
                    item_id=product_id,
                    pincode=loc["pincode"],
                    lat=loc["lat"],
                    lon=loc["lng"],
                    city=loc["name"],
                    store_id=loc["store_id"],
                    proxy_manager=proxy_manager,
                ),
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
        raise HTTPException(status_code=409, detail="A instamart scrape run is already in progress")
    from scheduler import run_manual_instamart_trigger
    asyncio.create_task(run_manual_instamart_trigger(request.app))
    return {"status": "started"}


@router.get("/instamart/cron-status")
async def instamart_cron_status(request: Request):
    """Return current instamart scrape status."""
    return dict(getattr(request.app.state, "instamart_cron_status", {}))
