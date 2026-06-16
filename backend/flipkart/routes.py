"""Flipkart price checking, manual scraping, and sheets API routes."""

import asyncio
import json
import logging
import os
from typing import List
from datetime import timezone, timedelta

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from flipkart.scraper import scrape_flipkart
from schemas.price import FlipkartRequest, FlipkartResponse
from utils.google_sheets import GoogleSheetsClient
from utils.scrape_helpers import batch_context, get_browser, sem_with_timeout

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# ── Flipkart Price Router ───────────────────────────────────────────────────

router = APIRouter(prefix="/price", tags=["Price"])


@router.post("/flipkart", response_model=FlipkartResponse)
async def check_flipkart_price(body: FlipkartRequest, request: Request):
    """Scrape Flipkart.in for product price by FSN."""
    cache = getattr(request.app.state, "cache", None)
    cache_key = f"flipkart_{body.fsn}"

    if cache is not None and cache_key in cache:
        result = cache[cache_key]
    else:
        proxy_manager = request.app.state.proxy_manager
        async with sem_with_timeout(request.app.state.total_sem):
            result = await scrape_flipkart(body.fsn, get_browser(request.app.state), proxy_manager)
            
        if cache is not None and result.get("status") not in ("error", "invalid_format"):
            cache[cache_key] = result

    return FlipkartResponse(
        fsn=result["fsn"],
        price=result.get("price", ""),
        mrp=result.get("mrp"),
        discount=result.get("discount"),
        rating=result.get("rating"),
        rating_count=result.get("rating_count"),
        status=result["status"],
        url=result["url"],
        resolved_url=result.get("resolved_url"),
        checked_at=result["checked_at"],
    )


# ── Manual Scrape Router (SSE) ──────────────────────────────────────────────

manual_router = APIRouter(prefix="/api/flipkart", tags=["Flipkart Manual"])


class ManualFSNScrapeRequest(BaseModel):
    fsns: List[str]


@manual_router.post("/scrape-manual")
async def scrape_manual_flipkart(body: ManualFSNScrapeRequest, request: Request):
    """Scrape a list of FSNs manually. Results are streamed via SSE — no sheet writes."""
    proxy_manager = request.app.state.proxy_manager

    if not request.app.state.playwright_ready:
        raise HTTPException(status_code=503, detail="Playwright browser not available")

    # Clean and deduplicate
    raw_fsns = [f.strip() for f in body.fsns if f.strip()]
    seen = set()
    clean_fsns = []
    for fsn in raw_fsns:
        if fsn in seen:
            continue
        seen.add(fsn)
        clean_fsns.append(fsn)

    if not clean_fsns:
        raise HTTPException(status_code=400, detail="No FSNs provided")

    total = len(clean_fsns)
    queue: asyncio.Queue = asyncio.Queue()
    app_state = request.app.state

    async def worker(fsn: str) -> None:
        cache = getattr(app_state, "cache", None)
        cache_key = f"flipkart_{fsn}"
        
        if cache is not None and cache_key in cache:
            result = cache[cache_key].copy()
        else:
            async with batch_context(app_state):
                result = await scrape_flipkart(fsn, get_browser(app_state), proxy_manager)
                
            if cache is not None and result.get("status") not in ("error", "invalid_format"):
                cache[cache_key] = result.copy()
                
        await queue.put(result)

    async def event_stream():
        tasks = [asyncio.create_task(worker(f)) for f in clean_fsns]
        done = 0

        while done < total:
            result = await queue.get()
            done += 1
            payload = json.dumps({**result, "progress": done, "total": total})
            yield f"data: {payload}\n\n"

        await asyncio.gather(*tasks, return_exceptions=True)
        yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Sheets Router ───────────────────────────────────────────────────────────

sheets_router = APIRouter(prefix="/sheets/flipkart", tags=["Flipkart Sheets"])


def get_sheets_client(request: Request):
    """Dependency injection for Google Sheets client."""
    return request.app.state.sheets_client


class FlipkartConfigResponse(BaseModel):
    flipkart_sheet_id: str
    flipkart_source_tab: str


class FlipkartPreviewRequest(BaseModel):
    sheet_id: str
    tab_name: str


class FlipkartPreviewResponse(BaseModel):
    status: str
    total_rows: int
    data: List[dict]


@sheets_router.get("/config", response_model=FlipkartConfigResponse)
async def get_flipkart_config():
    """Returns Flipkart sheet config from environment variables."""
    return FlipkartConfigResponse(
        flipkart_sheet_id=os.getenv("FLIPKART_SHEET_ID", ""),
        flipkart_source_tab=os.getenv("FLIPKART_SOURCE_TAB", "Sheet1"),
    )


@sheets_router.get("/list-tabs")
async def list_flipkart_tabs(sheet_id: str, sheets_client: GoogleSheetsClient = Depends(get_sheets_client)):
    """Returns all tab names in the Flipkart spreadsheet."""
    try:
        tabs = sheets_client.list_tabs(sheet_id)
        return {"status": "success", "tabs": tabs}
    except Exception as e:
        logger.exception("Failed to list Flipkart tabs")
        raise HTTPException(status_code=500, detail=str(e))


@sheets_router.post("/preview", response_model=FlipkartPreviewResponse)
async def preview_flipkart_sheet(body: FlipkartPreviewRequest, sheets_client: GoogleSheetsClient = Depends(get_sheets_client)):
    """Preview FSNs from a Flipkart sheet tab."""
    try:
        fsns = sheets_client.get_asins_with_rows(body.sheet_id, body.tab_name)
        return FlipkartPreviewResponse(
            status="success",
            total_rows=len(fsns),
            data=fsns,
        )
    except Exception as e:
        logger.exception("Failed to preview Flipkart sheet")
        raise HTTPException(status_code=500, detail=str(e))


@sheets_router.get("/products")
async def get_flipkart_products(sheets_client: GoogleSheetsClient = Depends(get_sheets_client)):
    """Return product catalog (id, title, brand) from the Flipkart source sheet."""
    sheet_id = os.getenv("FLIPKART_SHEET_ID", "")
    source_tab = os.getenv("FLIPKART_SOURCE_TAB", "Sheet1")
    if not sheet_id:
        raise HTTPException(status_code=503, detail="Flipkart sheet not configured (set FLIPKART_SHEET_ID)")
    try:
        return sheets_client.get_products_from_sheet(sheet_id, source_tab)
    except Exception as e:
        logger.exception("Failed to fetch Flipkart products")
        raise HTTPException(status_code=500, detail=str(e))


@sheets_router.post("/api/trigger-manual-scheduler")
async def trigger_manual_flipkart_scheduler(request: Request):
    """Trigger a full scrape of all Flipkart FSNs from the sheet, writing to a Flipkart_Manual tab."""
    if request.app.state.flipkart_cron_status.get("is_running"):
        raise HTTPException(status_code=409, detail="A Flipkart scrape run is already in progress")
    from scheduler import run_manual_flipkart_trigger
    task = asyncio.create_task(run_manual_flipkart_trigger(request.app))
    request.app.state.flipkart_cron_task = task
    return {"status": "started"}


@sheets_router.post("/api/cancel-manual-scheduler")
async def cancel_manual_flipkart_scheduler(request: Request):
    """Cancel a running Flipkart manual scrape."""
    task = request.app.state.flipkart_cron_task
    if task and not task.done():
        task.cancel()
        return {"status": "cancelling"}
    raise HTTPException(status_code=409, detail="No running Flipkart scrape to cancel")


@sheets_router.get("/cron-status")
async def flipkart_cron_status(request: Request):
    """Return current Flipkart sheet scrape status."""
    return dict(getattr(request.app.state, "flipkart_cron_status", {}))
