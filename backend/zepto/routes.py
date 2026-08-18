"""Zepto price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
import os

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from zepto.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from zepto.browser_scraper import scrape_one, sweep_city
from schemas.price import ZeptoRequest, ZeptoAllCitiesRequest, ZeptoResponse
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import batch_context, sem_with_timeout

logger = logging.getLogger(__name__)

router = APIRouter(tags=["zepto"])

ZEPTO_CITY_SWEEP_TIMEOUT = int(os.getenv("ZEPTO_CITY_SWEEP_TIMEOUT_SECONDS", "300"))


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
    Scrape Zepto for one or more product IDs across all cities.
    Grouped by city (one sweep_city() call per city) so location-setup (home
    nav + address click) is paid once per city instead of once per
    (product, city) pair — scrape_one() per pair used to redo it every time.
    Results are streamed as SSE events as they complete.
    """
    pids = [pid.strip() for pid in body.product_ids]
    total = len(pids) * len(LOCATIONS)

    if total == 0:
        async def empty_stream():
            yield f"data: {json.dumps({'done': True, 'total': 0})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    async def city_worker(loc: dict, queue: asyncio.Queue) -> None:
        cache = getattr(request.app.state, "cache", None)
        pending = []
        for pid in pids:
            cache_key = f"zepto_{pid}_{loc['name']}"
            if cache is not None and cache_key in cache:
                await queue.put(cache[cache_key].copy())
            else:
                pending.append(pid)

        if not pending:
            return

        browser = await request.app.state.browser_manager.acquire() if getattr(request.app.state, "browser_manager", None) else None
        if not browser:
            for pid in pending:
                await queue.put({"product_id": pid, "city": loc["name"], "status": "error",
                        "error_message": "browser pool unavailable", "price": None, "mrp": None,
                        "title": None, "is_sold_out": False, "url": None, "checked_at": None})
            return

        def _on_result(pid: str, r: dict) -> None:
            if cache is not None and r.get("status") not in ("error", "invalid_format"):
                cache[f"zepto_{pid}_{loc['name']}"] = r.copy()
            queue.put_nowait(r)

        try:
            async with batch_context(request.app.state):
                await asyncio.wait_for(
                    sweep_city(browser, loc, pending, on_result=_on_result),
                    timeout=ZEPTO_CITY_SWEEP_TIMEOUT,
                )
        except Exception as e:
            logger.exception("[Zepto] %s: sweep failed", loc["name"])
            for pid in pending:
                await queue.put({"product_id": pid, "city": loc["name"], "status": "error",
                        "error_message": str(e), "price": None, "mrp": None,
                        "title": None, "is_sold_out": False, "url": None, "checked_at": None})

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        tasks = [asyncio.create_task(city_worker(loc, queue)) for loc in LOCATIONS]
        done = 0
        try:
            while done < total:
                result = await queue.get()
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
