import asyncio
import json
import logging
import os
from typing import Any, List, Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from scrapers.amazon import scrape_amazon
from utils.google_sheets import GoogleSheetsClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sheets", tags=["Sheets"])

IST = timezone(timedelta(hours=5, minutes=30))

# 3 concurrent sessions per proxy — raise to 40 if proxies hold up, lower if blocks increase
SCRAPE_CONCURRENCY = 30
CHUNK_SIZE = 50


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
    rows: List[ScrapeRow]

class PreviewResponse(BaseModel):
    status: str
    total_rows: int
    data: List[dict]

class ConfigResponse(BaseModel):
    spreadsheet_id: str
    worksheet_name: str


def _format_update(res: dict) -> dict:
    return {
        "row": res["row"],
        "values": [
            res.get("price", ""),
            res.get("rating", ""),
            res.get("rating_count", ""),
            res.get("parent_node", ""),
            res.get("child_node", ""),
            res.get("status", "unknown"),
            res.get("checked_at", ""),
        ],
    }


async def _scrape_with_sem(sem: asyncio.Semaphore, asin: str, row: int, browser, proxy_manager) -> dict:
    async with sem:
        result = await scrape_amazon(asin, browser, proxy_manager)
        result["row"] = row
        return result


@router.get("/config", response_model=ConfigResponse)
async def get_config():
    """Returns default config from environment variables."""
    return ConfigResponse(
        spreadsheet_id=os.getenv("SPREADSHEET_ID", ""),
        worksheet_name=os.getenv("WORKSHEET_NAME", "Sheet1")
    )

@router.get("/list-tabs")
async def list_tabs(sheet_id: str, sheets_client: GoogleSheetsClient = Depends(get_sheets_client)):
    """Returns all tab names in the spreadsheet — use this to find the correct tab name."""
    try:
        tabs = sheets_client.list_tabs(sheet_id)
        return {"status": "success", "tabs": tabs}
    except Exception as e:
        logger.exception("Failed to list tabs")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/preview", response_model=PreviewResponse)
async def preview_sheet(body: PreviewRequest, sheets_client: GoogleSheetsClient = Depends(get_sheets_client)):
    try:
        asins = sheets_client.get_asins_with_rows(body.sheet_id, body.tab_name)
        return PreviewResponse(
            status="success",
            total_rows=len(asins),
            data=asins
        )
    except Exception as e:
        logger.exception("Failed to preview sheet")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scrape-batch")
async def scrape_batch(
    body: ScrapeBatchRequest,
    request: Request,
    sheets_client: GoogleSheetsClient = Depends(get_sheets_client),
):
    """Scrape all ASINs with concurrency control, writing to sheets every 50 results."""
    browser = request.app.state.playwright_browser
    proxy_manager = request.app.state.proxy_manager

    if not body.rows:
        return {"status": "success", "message": "No rows to process", "data": []}

    sem = asyncio.Semaphore(SCRAPE_CONCURRENCY)
    all_results: list[dict] = []

    for chunk_start in range(0, len(body.rows), CHUNK_SIZE):
        chunk = body.rows[chunk_start : chunk_start + CHUNK_SIZE]
        chunk_results = await asyncio.gather(
            *[_scrape_with_sem(sem, r.asin, r.row, browser, proxy_manager) for r in chunk]
        )
        updates = [_format_update(res) for res in chunk_results]
        try:
            sheets_client.batch_update_rows(body.sheet_id, body.tab_name, updates)
            logger.info("Wrote chunk rows %d–%d to sheets", chunk[0].row, chunk[-1].row)
        except Exception:
            logger.exception("Sheets write failed for chunk starting row %d", chunk[0].row)
        all_results.extend(chunk_results)

    return {"status": "success", "processed": len(all_results), "data": all_results}


@router.post("/scrape-batch-stream")
async def scrape_batch_stream(
    body: ScrapeBatchRequest,
    request: Request,
    sheets_client: GoogleSheetsClient = Depends(get_sheets_client),
):
    """Stream scrape results as SSE events. Each ASIN result is sent as it completes.
    Sheets are written every 50 results. Final event: {"done": true, "total": N}."""
    browser = request.app.state.playwright_browser
    proxy_manager = request.app.state.proxy_manager
    sem = asyncio.Semaphore(SCRAPE_CONCURRENCY)
    queue: asyncio.Queue = asyncio.Queue()
    total = len(body.rows)

    if total == 0:
        async def empty_stream():
            yield f"data: {json.dumps({'done': True, 'total': 0})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    async def worker(row_data: ScrapeRow) -> None:
        async with sem:
            result = await scrape_amazon(row_data.asin, browser, proxy_manager)
            result["row"] = row_data.row
            await queue.put(result)

    async def event_stream():
        tasks = [asyncio.create_task(worker(r)) for r in body.rows]
        done = 0
        pending_updates: list[dict] = []

        while done < total:
            result = await queue.get()
            done += 1
            pending_updates.append(_format_update(result))

            if len(pending_updates) >= CHUNK_SIZE or done == total:
                try:
                    sheets_client.batch_update_rows(body.sheet_id, body.tab_name, pending_updates)
                    logger.info("Stream: wrote %d rows to sheets (%d/%d done)", len(pending_updates), done, total)
                except Exception:
                    logger.exception("Stream: sheets write failed at progress %d/%d", done, total)
                pending_updates = []

            payload = json.dumps({**result, "progress": done, "total": total})
            yield f"data: {payload}\n\n"

        await asyncio.gather(*tasks, return_exceptions=True)
        yield f"data: {json.dumps({'done': True, 'total': total})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
