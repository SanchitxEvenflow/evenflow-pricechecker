"""Blinkit price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
from functools import partial

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from blinkit.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from blinkit.scraper import fetch_blinkit_data
from schemas.price import BlinkitRequest, BlinkitAllCitiesRequest, BlinkitResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["blinkit"])


# ── Single city lookup ──────────────────────────────────────────────────────

@router.post("/blinkit", response_model=BlinkitResponse)
async def check_blinkit_price(body: BlinkitRequest, request: Request):
    """Scrape Blinkit for a single product in a single city."""
    city_data = LOCATIONS_BY_CITY.get(body.city)
    if not city_data:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid city '{body.city}'. Valid cities: {CITY_NAMES}",
        )

    proxy_manager = request.app.state.proxy_manager

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        request.app.state.thread_pool,
        partial(
            fetch_blinkit_data,
            item_id=body.product_id,
            pincode=city_data["pincode"],
            lat=city_data["lat"],
            lon=city_data["lng"],
            city=body.city,
            proxy_manager=proxy_manager,
        ),
    )

    return BlinkitResponse(**result)


# ── All cities SSE stream ──────────────────────────────────────────────────

BLINKIT_CONCURRENCY = 5  # Blinkit rate-limits aggressively


@router.post("/blinkit/all-cities")
async def check_blinkit_all_cities(body: BlinkitAllCitiesRequest, request: Request):
    """
    Scrape Blinkit for one or more product IDs across all 10 cities.
    Results are streamed as SSE events as they complete.
    """
    proxy_manager = request.app.state.proxy_manager
    sem = asyncio.Semaphore(BLINKIT_CONCURRENCY)
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
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                request.app.state.thread_pool,
                partial(
                    fetch_blinkit_data,
                    item_id=product_id,
                    pincode=loc["pincode"],
                    lat=loc["lat"],
                    lon=loc["lng"],
                    city=loc["name"],
                    proxy_manager=proxy_manager,
                ),
            )
            await queue.put(result)

    async def event_stream():
        tasks = [asyncio.create_task(worker(pid, loc)) for pid, loc in work_items]
        done = 0

        while done < total:
            result = await queue.get()
            done += 1
            payload = json.dumps({
                **result,
                "progress": done,
                "total": total,
            })
            yield f"data: {payload}\n\n"

        # Ensure all tasks are finished
        await asyncio.gather(*tasks, return_exceptions=True)
        yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Sheet-based manual trigger ──────────────────────────────────────────────

@router.post("/blinkit/api/trigger-manual-scheduler")
async def trigger_manual_blinkit(request: Request):
    """Trigger a full Blinkit scrape of all PIDs from the sheet (runs in background)."""
    if request.app.state.blinkit_cron_status.get("is_running"):
        raise HTTPException(status_code=409, detail="A Blinkit scrape run is already in progress")
    from scheduler import run_manual_blinkit_trigger
    asyncio.create_task(run_manual_blinkit_trigger(request.app))
    return {"status": "started"}


@router.get("/blinkit/cron-status")
async def blinkit_cron_status(request: Request):
    """Return current Blinkit scrape status."""
    return dict(getattr(request.app.state, "blinkit_cron_status", {}))
