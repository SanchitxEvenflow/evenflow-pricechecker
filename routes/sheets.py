import asyncio
import logging
import os
from typing import Any, List, Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel

from scrapers.amazon import scrape_amazon
from utils.google_sheets import GoogleSheetsClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sheets", tags=["Sheets"])

IST = timezone(timedelta(hours=5, minutes=30))

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
async def scrape_batch(body: ScrapeBatchRequest, request: Request, sheets_client: GoogleSheetsClient = Depends(get_sheets_client)):
    proxy_manager = request.app.state.proxy_manager
    browser = request.app.state.playwright_browser

    if not body.rows:
        return {"status": "success", "message": "No rows to process", "data": []}

    results = []
    
    # Scrape all ASINs concurrently
    tasks = []
    for row_data in body.rows:
        tasks.append(scrape_amazon(row_data.asin, browser, proxy_manager))
        
    scraped_data = await asyncio.gather(*tasks)
    
    # Prepare update payload
    updates = []
    response_data = []
    
    for i, row_data in enumerate(body.rows):
        res = scraped_data[i]
        
        # Format the values for columns B through H
        # Column B: Price
        # Column C: Rating
        # Column D: Rating Count
        # Column E: Parent Node
        # Column F: Child Node
        # Column G: Status
        # Column H: Checked At
        
        vals = [
            res.get("price", ""),
            res.get("rating", ""),
            res.get("rating_count", ""),
            res.get("parent_node", ""),
            res.get("child_node", ""),
            res.get("status", "unknown"),
            res.get("checked_at", "")
        ]
        
        updates.append({
            "row": row_data.row,
            "values": vals
        })
        
        res["row"] = row_data.row
        response_data.append(res)
        
    # Write to Google Sheets
    try:
        sheets_client.batch_update_rows(body.sheet_id, body.tab_name, updates)
    except Exception as e:
        logger.exception("Failed to write batch to Google Sheets")
        raise HTTPException(status_code=500, detail=f"Failed to write to sheets: {str(e)}")
        
    return {
        "status": "success",
        "processed": len(response_data),
        "data": response_data
    }
