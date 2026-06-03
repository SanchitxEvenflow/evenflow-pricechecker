"""Flipkart price checking API routes."""

import logging
from datetime import timezone, timedelta

from fastapi import APIRouter, Request

from flipkart.scraper import scrape_flipkart
from schemas.price import FlipkartRequest, FlipkartResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/price", tags=["Price"])

IST = timezone(timedelta(hours=5, minutes=30))


@router.post("/flipkart", response_model=FlipkartResponse)
async def check_flipkart_price(body: FlipkartRequest, request: Request):
    """Scrape Flipkart.in for product price by FSN."""
    proxy_manager = request.app.state.proxy_manager
    browser = request.app.state.playwright_browser

    result = await scrape_flipkart(body.fsn, browser, proxy_manager)

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
