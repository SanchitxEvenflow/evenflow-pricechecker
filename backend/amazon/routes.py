"""Amazon price checking & sheets API routes."""

import asyncio
import json
import logging
import os
import re
from typing import List
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from amazon.scraper import scrape_amazon, fetch_curl_supplement, merge_curl_supplement
from schemas.price import AmazonRequest, AmazonResponse
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import CHUNK_SIZE, SCRAPE_CONCURRENCY, batch_context, format_update, get_browser, sem_with_timeout

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# ── Amazon Price Router ─────────────────────────────────────────────────────

price_router = APIRouter(prefix="/price", tags=["Price"])


@price_router.post("/amazon", response_model=AmazonResponse)
async def check_amazon_price(body: AmazonRequest, request: Request):
    """Scrape Amazon.in for product price by ASIN."""
    cache = getattr(request.app.state, "cache", None)
    cache_key = f"amazon_{body.asin}"
    
    if cache is not None and cache_key in cache:
        result = cache[cache_key]
    else:
        proxy_manager = request.app.state.proxy_manager
        async with sem_with_timeout(request.app.state.total_sem):
            result = await scrape_amazon(body.asin, get_browser(request.app.state), proxy_manager, skip_curl=True, browser_manager=request.app.state.browser_manager)
        cookies = result.pop("_cookies", {}) or {}
        if cookies:
            curl_data = await fetch_curl_supplement(body.asin, cookies)
            merge_curl_supplement(result, curl_data)
        
        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result

    return AmazonResponse(
        asin=result["asin"],
        price=result.get("price", ""),
        mrp=result.get("mrp"),
        rating=result.get("rating"),
        rating_count=result.get("rating_count"),
        rating_breakdown=result.get("rating_breakdown"),
        rank_raw=result.get("rank_raw"),
        rank_value=result.get("rank_value"),
        rank_category=result.get("rank_category"),
        sub_rank_value=result.get("sub_rank_value"),
        sub_rank_category=result.get("sub_rank_category"),
        parent_node=result.get("parent_node"),
        child_node=result.get("child_node"),
        category_path=result.get("category_path"),
        status=result["status"],
        url=result["url"],
        checked_at=result["checked_at"],
    )


# ── Sheets Router ───────────────────────────────────────────────────────────

sheets_router = APIRouter(prefix="/sheets/amazon", tags=["Sheets"])


def get_sheets_client():
    return GoogleSheetsClient()


class PreviewRequest(BaseModel):
    sheet_id: str
    tab_name: str

class ScrapeRow(BaseModel):
    row: int
    asin: str

class ScrapeBatchRequest(BaseModel):
    sheet_id: str
    tab_name: str
    rows: List[dict]

class PreviewResponse(BaseModel):
    status: str
    total_rows: int
    data: List[dict]

class ConfigResponse(BaseModel):
    spreadsheet_id: str
    worksheet_name: str


_format_update = format_update


async def _scrape_with_sem(asin: str, row: int, app_state, proxy_manager) -> dict:
    async with batch_context(app_state):
        result = await scrape_amazon(asin, get_browser(app_state), proxy_manager, skip_curl=True, browser_manager=app_state.browser_manager)
        result["row"] = row
    cookies = result.pop("_cookies", {}) or {}
    if cookies:
        curl_data = await fetch_curl_supplement(asin, cookies)
        merge_curl_supplement(result, curl_data)
    return result


@sheets_router.get("/config", response_model=ConfigResponse)
async def get_config():
    """Returns default config from environment variables."""
    return ConfigResponse(
        spreadsheet_id=os.getenv("SPREADSHEET_ID", ""),
        worksheet_name=os.getenv("WORKSHEET_NAME", "Sheet1")
    )

@sheets_router.get("/list-tabs")
async def list_tabs(sheet_id: str, sheets_client: GoogleSheetsClient = Depends(get_sheets_client)):
    """Returns all tab names in the spreadsheet — use this to find the correct tab name."""
    try:
        tabs = await asyncio.get_running_loop().run_in_executor(None, sheets_client.list_tabs, sheet_id)
        return {"status": "success", "tabs": tabs}
    except Exception as e:
        logger.exception("Failed to list tabs")
        raise HTTPException(status_code=500, detail=str(e))

@sheets_router.post("/preview", response_model=PreviewResponse)
async def preview_sheet(body: PreviewRequest, sheets_client: GoogleSheetsClient = Depends(get_sheets_client)):
    try:
        asins = await asyncio.get_running_loop().run_in_executor(
            None, sheets_client.get_asins_with_rows, body.sheet_id, body.tab_name)
        return PreviewResponse(
            status="success",
            total_rows=len(asins),
            data=asins
        )
    except Exception as e:
        logger.exception("Failed to preview sheet")
        raise HTTPException(status_code=500, detail=str(e))


@sheets_router.get("/products")
async def get_amazon_products(sheets_client: GoogleSheetsClient = Depends(get_sheets_client)):
    """Return product catalog (id, title, brand) from the Amazon source sheet."""
    sheet_id = os.getenv("CRON_SHEET_ID") or os.getenv("SPREADSHEET_ID", "")
    source_tab = os.getenv("CRON_SOURCE_TAB") or os.getenv("WORKSHEET_NAME", "Sheet1")
    if not sheet_id:
        raise HTTPException(status_code=503, detail="Amazon sheet not configured (set SPREADSHEET_ID)")
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, sheets_client.get_products_from_sheet, sheet_id, source_tab)
    except Exception as e:
        logger.exception("Failed to fetch Amazon products")
        raise HTTPException(status_code=500, detail=str(e))


@sheets_router.post("/cron-trigger")
async def cron_trigger(request: Request):
    """Manually fire the scheduled scrape job immediately (runs in background)."""
    if request.app.state.cron_status.get("is_running"):
        raise HTTPException(status_code=409, detail="A cron run is already in progress")
    from scheduler import run_scheduled_scrape  # lazy import — avoids circular dependency
    asyncio.create_task(run_scheduled_scrape(request.app))
    return {"status": "started"}


@sheets_router.get("/cron-status")
async def cron_status(request: Request):
    """Return current cron scheduler status and next run time."""
    status = dict(getattr(request.app.state, "cron_status", {}))
    scheduler = getattr(request.app.state, "cron_scheduler", None)
    if scheduler:
        job = scheduler.get_job("scheduled_scrape")
        status["next_run_at"] = job.next_run_time.isoformat() if (job and job.next_run_time) else None
        status["scheduler_enabled"] = True
    else:
        status["next_run_at"] = None
        status["scheduler_enabled"] = False
    return status


# ── New API endpoints ──────────────────────────────────────────────────────

@sheets_router.post("/api/trigger-manual-scheduler")
async def trigger_manual_scheduler(request: Request):
    """Trigger a full scrape of all sheet ASINs, writing to a Manual_Trigger tab."""
    if request.app.state.cron_status.get("is_running"):
        raise HTTPException(status_code=409, detail="A scrape run is already in progress")
    from scheduler import run_manual_trigger
    task = asyncio.create_task(run_manual_trigger(request.app))
    request.app.state.cron_task = task
    return {"status": "started"}


@sheets_router.post("/api/cancel-manual-scheduler")
async def cancel_manual_scheduler(request: Request):
    """Cancel a running Amazon manual scrape."""
    task = request.app.state.cron_task
    if task and not task.done():
        task.cancel()
        return {"status": "cancelling"}
    raise HTTPException(status_code=409, detail="No running scrape to cancel")

@sheets_router.post("/api/trigger-manual-blinkit")
async def trigger_manual_blinkit(request: Request):
    """Trigger a full scrape of all Blinkit PIDs across 10 cities."""
    if request.app.state.blinkit_cron_status.get("is_running"):
        raise HTTPException(status_code=409, detail="A Blinkit scrape run is already in progress")
    from scheduler import run_manual_blinkit_trigger
    asyncio.create_task(run_manual_blinkit_trigger(request.app))
    return {"status": "started"}



@sheets_router.get("/api/logs")
async def get_logs():
    """Return all scraper run logs, newest first."""
    from utils.run_logger import get_all_logs
    return {"status": "success", "logs": get_all_logs()}


@sheets_router.post("/scrape-batch")
async def scrape_batch(
    body: ScrapeBatchRequest,
    request: Request,
    sheets_client: GoogleSheetsClient = Depends(get_sheets_client),
):
    """Scrape all ASINs with concurrency control, writing to sheets every 50 results."""
    proxy_manager = request.app.state.proxy_manager

    if not body.rows:
        return {"status": "success", "message": "No rows to process", "data": []}

    all_results: list[dict] = []
    pending_writes: list[dict] = []

    tasks = [
        asyncio.create_task(_scrape_with_sem(r["asin"], r["row"], request.app.state, proxy_manager))
        for r in body.rows
    ]

    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
        except Exception:
            logger.exception("scrape_batch: task raised unexpectedly")
            continue
        all_results.append(result)
        pending_writes.append(_format_update(result))

        if len(pending_writes) >= CHUNK_SIZE:
            try:
                await sheets_client.async_batch_update_rows(body.sheet_id, body.tab_name, pending_writes)
                logger.info("scrape_batch: wrote %d rows (%d/%d done)",
                            len(pending_writes), len(all_results), len(body.rows))
            except Exception:
                logger.exception("scrape_batch: sheets write failed")
            pending_writes = []

    if pending_writes:
        try:
            await sheets_client.async_batch_update_rows(body.sheet_id, body.tab_name, pending_writes)
            logger.info("scrape_batch: wrote final %d rows", len(pending_writes))
        except Exception:
            logger.exception("scrape_batch: final sheets write failed")

    return {"status": "success", "processed": len(all_results), "data": all_results}


@sheets_router.post("/scrape-batch-stream")
async def scrape_batch_stream(
    body: ScrapeBatchRequest,
    request: Request,
    sheets_client: GoogleSheetsClient = Depends(get_sheets_client),
):
    """Stream scrape results as SSE events. Each ASIN result is sent as it completes.
    Sheets are written every 50 results. Final event: {"done": true, "total": N}."""
    proxy_manager = request.app.state.proxy_manager
    queue: asyncio.Queue = asyncio.Queue()
    total = len(body.rows)

    if total == 0:
        async def empty_stream():
            yield f"data: {json.dumps({'done': True, 'total': 0})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    app_state = request.app.state

    async def worker(row_data: dict) -> None:
        async with batch_context(app_state):
            result = await scrape_amazon(row_data["asin"], get_browser(app_state), proxy_manager, skip_curl=True, browser_manager=app_state.browser_manager)
            result["row"] = row_data["row"]
        try:
            cookies = result.pop("_cookies", {}) or {}
            if cookies:
                curl_data = await fetch_curl_supplement(row_data["asin"], cookies)
                merge_curl_supplement(result, curl_data)
        except Exception:
            logger.exception("scrape_batch_stream: curl supplement failed for ASIN %s", row_data["asin"])
        await queue.put(result)

    async def event_stream():
        tasks = [asyncio.create_task(worker(r)) for r in body.rows]
        done = 0
        pending_updates: list[dict] = []

        while done < total:
            try:
                result = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            done += 1
            pending_updates.append(_format_update(result))

            if len(pending_updates) >= CHUNK_SIZE or done == total:
                try:
                    await sheets_client.async_batch_update_rows(body.sheet_id, body.tab_name, pending_updates)
                    logger.info("Stream: wrote %d rows to sheets (%d/%d done)", len(pending_updates), done, total)
                except Exception:
                    logger.exception("Stream: sheets write failed at progress %d/%d", done, total)
                pending_updates = []

            payload = json.dumps({**result, "progress": done, "total": total})
            yield f"data: {payload}\n\n"

        await asyncio.gather(*tasks, return_exceptions=True)
        yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Manual Scrape Router ────────────────────────────────────────────────────

manual_router = APIRouter(prefix="/api/amazon", tags=["Manual"])


class ManualScrapeRequest(BaseModel):
    asins: List[str]


def _validate_asin(asin: str) -> bool:
    """ASIN must be exactly 10 alphanumeric characters."""
    return bool(re.match(r"^[A-Z0-9]{10}$", asin.strip().upper()))


@manual_router.post("/scrape-manual")
async def scrape_manual(body: ManualScrapeRequest, request: Request):
    """Scrape a list of ASINs manually. Results are streamed via SSE — no sheet writes."""
    proxy_manager = request.app.state.proxy_manager

    if not request.app.state.playwright_ready:
        raise HTTPException(status_code=503, detail="Playwright browser not available")

    # Clean, deduplicate, validate
    raw_asins = [a.strip().upper() for a in body.asins if a.strip()]
    seen = set()
    clean_asins = []
    invalid_asins = []

    for asin in raw_asins:
        if asin in seen:
            continue
        seen.add(asin)
        if _validate_asin(asin):
            clean_asins.append(asin)
        else:
            invalid_asins.append(asin)

    if not clean_asins and not invalid_asins:
        raise HTTPException(status_code=400, detail="No ASINs provided")

    total = len(clean_asins) + len(invalid_asins)
    queue: asyncio.Queue = asyncio.Queue()
    app_state = request.app.state

    # Push invalid ASINs as immediate errors
    for asin in invalid_asins:
        await queue.put({
            "asin": asin,
            "price": "",
            "rating": None,
            "rating_count": None,
            "status": "invalid_format",
            "url": "",
            "checked_at": "",
        })

    # Bounded worker pool: exactly N workers drain a shared ASIN queue instead of
    # spawning one task per ASIN. At 800 ASINs this is what keeps us safe —
    # workers block on total_sem (the global browser hard-cap) with no per-task
    # acquire deadline, so no ASIN is ever dropped and the stream always completes.
    asins_in: asyncio.Queue = asyncio.Queue()
    for asin in clean_asins:
        asins_in.put_nowait(asin)

    async def scrape_one(asin: str) -> dict:
        cache = getattr(app_state, "cache", None)
        cache_key = f"amazon_{asin}"

        if cache is not None and cache_key in cache:
            return cache[cache_key].copy()

        # total_sem is the global hard cap on live browser contexts. Plain acquire
        # (no timeout): MANUAL_RESERVED guarantees batch runs can never hold every
        # slot, so a manual worker always gets one within one scrape-cycle.
        async with app_state.total_sem:
            result = await scrape_amazon(
                asin, get_browser(app_state), proxy_manager,
                skip_curl=True, browser_manager=app_state.browser_manager,
            )
        try:
            cookies = result.pop("_cookies", {}) or {}
            if cookies:
                curl_data = await fetch_curl_supplement(asin, cookies)
                merge_curl_supplement(result, curl_data)
        except Exception:
            logger.exception("scrape_manual: curl supplement failed for ASIN %s", asin)

        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result.copy()
        return result

    async def worker() -> None:
        while True:
            try:
                asin = asins_in.get_nowait()
            except asyncio.QueueEmpty:
                return
            # Fallback result so a crash still emits exactly one message per ASIN —
            # the stream counts to `total` and would hang forever if any were lost.
            result = {
                "asin": asin, "price": "", "rating": None, "rating_count": None,
                "status": "error", "url": "", "checked_at": "",
            }
            try:
                scraped = await scrape_one(asin)
                if scraped:
                    result = scraped
            except asyncio.CancelledError:
                raise  # client disconnected — don't emit, let cancellation propagate
            except Exception:
                logger.exception("scrape_manual: worker failed for ASIN %s", asin)
            await queue.put(result)

    async def event_stream():
        n_workers = min(SCRAPE_CONCURRENCY, len(clean_asins))
        workers = [asyncio.create_task(worker()) for _ in range(n_workers)]
        try:
            emitted = 0
            while emitted < total:
                try:
                    result = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                emitted += 1
                payload = json.dumps({**result, "progress": emitted, "total": total})
                yield f"data: {payload}\n\n"
            yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"
        finally:
            # Normal end (workers already done) or client disconnect: cancel any
            # stragglers so we never orphan browser/proxy work after the socket closes.
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
