"""Blinkit price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
import os
from functools import partial

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from blinkit.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from blinkit.scraper import fetch_blinkit_city, fetch_blinkit_data
from proxy.socks5_provider import get_provider as get_snowpad_provider
from schemas.price import BlinkitRequest, BlinkitAllCitiesRequest, BlinkitResponse
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import batch_context, sem_with_timeout, unique_queue_results

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

    cache = getattr(request.app.state, "cache", None)
    cache_key = f"blinkit_{body.product_id}_{body.city}"

    if cache is not None and cache_key in cache:
        result = cache[cache_key]
    else:
        loop = asyncio.get_running_loop()
        snowpad = get_snowpad_provider()
        async with sem_with_timeout(request.app.state.total_sem):
            await snowpad.acquire_slot()
            try:
                result = await loop.run_in_executor(
                    request.app.state.thread_pool,
                    partial(
                        fetch_blinkit_data,
                        item_id=body.product_id,
                        pincode=city_data["pincode"],
                        lat=city_data["lat"],
                        lon=city_data["lng"],
                        city=body.city,
                    ),
                )
            finally:
                snowpad.release_slot()
        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result

    return BlinkitResponse(**result)


# ── All cities SSE stream ──────────────────────────────────────────────────


@router.post("/blinkit/all-cities")
async def check_blinkit_all_cities(body: BlinkitAllCitiesRequest, request: Request):
    """
    Scrape Blinkit for one or more product IDs across all 10 cities.
    Results are streamed as SSE events as they complete.
    """
    pids = list(dict.fromkeys(pid.strip() for pid in body.product_ids if pid.strip()))
    total = len(pids) * len(LOCATIONS)

    if total == 0:
        async def empty_stream():
            yield f"data: {json.dumps({'done': True, 'total': 0})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    city_sem = asyncio.Semaphore(max(1, int(os.getenv("BLINKIT_CONCURRENCY", "6"))))

    async def city_worker(loc: dict, queue: asyncio.Queue) -> None:
        city = loc["name"]
        cache = getattr(request.app.state, "cache", None)
        pending = []
        emitted: set[str] = set()
        for pid in pids:
            cache_key = f"blinkit_{pid}_{city}"
            if cache is not None and cache_key in cache:
                emitted.add(pid)
                await queue.put(cache[cache_key].copy())
            else:
                pending.append(pid)

        if not pending:
            return

        loop = asyncio.get_running_loop()

        def on_result(pid: str, result: dict) -> None:
            emitted.add(pid)

            def enqueue() -> None:
                if cache is not None and result.get("status") not in ("error", "invalid_format"):
                    cache[f"blinkit_{pid}_{city}"] = result.copy()
                queue.put_nowait(result)

            loop.call_soon_threadsafe(enqueue)

        try:
            async with city_sem:
                async with batch_context(request.app.state):
                    snowpad = get_snowpad_provider()
                    await snowpad.acquire_slot()
                    try:
                        await loop.run_in_executor(
                            request.app.state.thread_pool,
                            partial(
                                fetch_blinkit_city,
                                item_ids=pending,
                                pincode=loc["pincode"],
                                lat=loc["lat"],
                                lon=loc["lng"],
                                city=city,
                                on_result=on_result,
                            ),
                        )
                    finally:
                        snowpad.release_slot()
        except Exception as exc:
            logger.exception("Blinkit city worker failed for %s", city)
            for pid in pending:
                if pid not in emitted:
                    await queue.put({"product_id": pid, "city": city, "status": "error",
                                     "error_message": str(exc)})

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        tasks = [asyncio.create_task(city_worker(loc, queue)) for loc in LOCATIONS]
        expected = {(pid, loc["name"]) for pid in pids for loc in LOCATIONS}
        done = 0
        async for result in unique_queue_results(queue, tasks, expected):
            if result is None:
                yield ": keep-alive\n\n"
                continue
            done += 1
            yield f"data: {json.dumps({**result, 'progress': done, 'total': total})}\n\n"
        yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


# ── Sheet-based manual trigger ──────────────────────────────────────────────

@router.post("/blinkit/api/trigger-manual-scheduler")
async def trigger_manual_blinkit(request: Request):
    """Trigger a full Blinkit scrape of all PIDs from the sheet (runs in background)."""
    if request.app.state.blinkit_cron_status.get("is_running"):
        raise HTTPException(status_code=409, detail="A Blinkit scrape run is already in progress")
    from scheduler import run_manual_blinkit_trigger
    task = asyncio.create_task(run_manual_blinkit_trigger(request.app))
    request.app.state.blinkit_cron_task = task
    return {"status": "started"}


@router.post("/blinkit/api/cancel-manual-scheduler")
async def cancel_manual_blinkit(request: Request):
    """Cancel a running Blinkit manual scrape."""
    task = request.app.state.blinkit_cron_task
    if task and not task.done():
        task.cancel()
        return {"status": "cancelling"}
    raise HTTPException(status_code=409, detail="No running Blinkit scrape to cancel")


@router.get("/blinkit/cron-status")
async def blinkit_cron_status(request: Request):
    """Return current Blinkit scrape status."""
    return dict(getattr(request.app.state, "blinkit_cron_status", {}))


@router.get("/blinkit/products")
async def get_blinkit_products():
    """Return product catalog (id, title, brand) from the Blinkit source sheet."""
    sheet_id = os.getenv("BLINKIT_SHEET_ID", "")
    source_tab = os.getenv("BLINKIT_SOURCE_TAB", "Sheet1")
    if not sheet_id:
        raise HTTPException(status_code=503, detail="Blinkit sheet not configured (set BLINKIT_SHEET_ID)")
    try:
        return GoogleSheetsClient().get_products_from_sheet(sheet_id, source_tab)
    except Exception as e:
        logger.exception("Failed to fetch Blinkit products")
        raise HTTPException(status_code=500, detail=str(e))
