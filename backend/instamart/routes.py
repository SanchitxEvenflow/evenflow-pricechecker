"""instamart price checking routes — single city & all-cities SSE stream."""

import asyncio
import json
import logging
import os

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from instamart.locations import LOCATIONS, LOCATIONS_BY_CITY, CITY_NAMES
from instamart.browser_scraper import scrape_one, sweep_city
from schemas.price import InstamartRequest, InstamartAllCitiesRequest, InstamartResponse
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import batch_context, sem_with_timeout, unique_queue_results

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
    product_id = body.product_id.strip().upper()
    cache_key = f"instamart_v3_{product_id}_{body.city}"

    if cache is not None and cache_key in cache:
        result = cache[cache_key]
    else:
        api = getattr(request.app.state, "instamart_api", None)
        if api is not None and city_data.get("store_id"):
            result = await api.scrape_one(product_id, city_data)
        else:
            browser = await request.app.state.browser_manager.acquire() if getattr(request.app.state, "browser_manager", None) else None
            if not browser:
                raise HTTPException(status_code=503, detail="Browser pool unavailable")
            async with sem_with_timeout(request.app.state.total_sem):
                result = await scrape_one(browser, city_data, product_id)
        if cache is not None and result.get("status") not in ("error", "invalid_format", "unresolved_product"):
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

    pids = list(dict.fromkeys(pid.strip().upper() for pid in body.product_ids if pid.strip()))
    total = len(pids) * len(LOCATIONS)

    if total == 0:
        async def empty_stream():
            yield f"data: {json.dumps({'done': True, 'total': 0})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    city_sem = asyncio.Semaphore(max(1, int(os.getenv("INSTAMART_CITY_CONCURRENCY", "3"))))

    async def browser_city_worker(loc: dict, queue: asyncio.Queue) -> None:
        city = loc["name"]
        cache = getattr(app_state, "cache", None)
        pending = []
        emitted: set[str] = set()
        for pid in pids:
            cache_key = f"instamart_v3_{pid}_{city}"
            if cache is not None and cache_key in cache:
                emitted.add(pid)
                await queue.put(cache[cache_key].copy())
            else:
                pending.append(pid)

        if not pending:
            return

        def on_result(pid: str, result: dict) -> None:
            emitted.add(pid)
            if cache is not None and result.get("status") not in ("error", "invalid_format", "unresolved_product"):
                cache[f"instamart_v3_{pid}_{city}"] = result.copy()
            queue.put_nowait(result)

        try:
            async with city_sem:
                browser = await app_state.browser_manager.acquire()
                async with batch_context(app_state):
                    await sweep_city(browser, loc, pending, on_result=on_result)
        except Exception as exc:
            logger.exception("[Instamart] %s: city sweep failed", city)
            for pid in pending:
                if pid not in emitted:
                    await queue.put({"product_id": pid, "city": city, "status": "error",
                                     "error_message": str(exc)})

    async def api_worker(locations: list[dict], queue: asyncio.Queue) -> None:
        cache = getattr(app_state, "cache", None)
        pairs = []
        emitted: set[tuple[str, str]] = set()
        for pid in pids:
            for loc in locations:
                key = (pid, loc["name"])
                cache_key = f"instamart_v3_{pid}_{loc['name']}"
                if cache is not None and cache_key in cache:
                    emitted.add(key)
                    await queue.put(cache[cache_key].copy())
                else:
                    pairs.append((pid, loc))

        def on_result(result: dict) -> None:
            key = (result["product_id"], result["city"])
            emitted.add(key)
            if cache is not None and result.get("status") not in ("error", "invalid_format", "unresolved_product"):
                cache[f"instamart_v3_{key[0]}_{key[1]}"] = result.copy()
            queue.put_nowait(result)

        if not pairs:
            return

        # Live testing found the app-level throttle is tied to the session cookie's
        # own quota (~135 requests), not elapsed time or source IP: reusing one
        # cookie across batches collapsed to 100% failure even with a 20s gap and
        # even with a rotated proxy IP, but re-minting the cookie before each batch
        # kept 3x135 back-to-back at ~0.25% failure with zero cooldown needed.
        batch_size = max(1, int(os.getenv("INSTAMART_PRODUCT_BATCH_SIZE", "15")))

        by_pid: dict[str, list[dict]] = {}
        for pid, loc in pairs:
            by_pid.setdefault(pid, []).append(loc)
        pid_batches = [pids_chunk for pids_chunk in
                       (list(by_pid.keys())[i:i + batch_size]
                        for i in range(0, len(by_pid), batch_size))]

        for batch_num, pid_batch in enumerate(pid_batches):
            batch_pairs = [(pid, loc) for pid in pid_batch for loc in by_pid[pid]]
            if batch_num > 0:
                await app_state.instamart_api._refresh_cookies()
            try:
                await app_state.instamart_api.scrape_pairs(batch_pairs, on_result=on_result)
            except Exception as exc:
                logger.exception("[Instamart API] batch %d/%d failed", batch_num + 1, len(pid_batches))
                for pid, loc in batch_pairs:
                    if (pid, loc["name"]) not in emitted:
                        await queue.put({"product_id": pid, "city": loc["name"], "status": "error",
                                         "error_message": str(exc)})

    async def event_stream():
        done = 0
        queue: asyncio.Queue = asyncio.Queue()
        api = getattr(app_state, "instamart_api", None)
        api_locations = [loc for loc in LOCATIONS if api is not None and loc.get("store_id")]
        browser_locations = [loc for loc in LOCATIONS if loc not in api_locations]
        tasks = [asyncio.create_task(browser_city_worker(loc, queue)) for loc in browser_locations]
        if api_locations:
            tasks.append(asyncio.create_task(api_worker(api_locations, queue)))
        expected = {(pid, loc["name"]) for pid in pids for loc in LOCATIONS}
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
