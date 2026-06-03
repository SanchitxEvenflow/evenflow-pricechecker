"""Price checking API routes."""

import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request

from schemas.price import (
    AmazonRequest,
    AmazonResponse,
    BothRequest,
    BothResponse,
    FlipkartRequest,
    FlipkartResponse,
)
from scrapers.amazon import scrape_amazon
from scrapers.flipkart import scrape_flipkart

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/price", tags=["Price"])

IST = timezone(timedelta(hours=5, minutes=30))

@router.post("/amazon", response_model=AmazonResponse)
async def check_amazon_price(body: AmazonRequest, request: Request):
    """Scrape Amazon.in for product price by ASIN."""
    proxy_manager = request.app.state.proxy_manager
    browser = request.app.state.playwright_browser

    result = await scrape_amazon(body.asin, browser, proxy_manager)

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


@router.post("/both", response_model=BothResponse)
async def check_both_prices(body: BothRequest, request: Request):
    """Scrape both Amazon.in and Flipkart.in in parallel."""
    proxy_manager = request.app.state.proxy_manager
    browser = request.app.state.playwright_browser

    # Run both scrapers in parallel
    amazon_task = scrape_amazon(body.asin, browser, proxy_manager)
    flipkart_task = scrape_flipkart(body.fsn, browser, proxy_manager)

    amazon_result, flipkart_result = await asyncio.gather(amazon_task, flipkart_task)

    # Calculate price difference
    price_diff, cheaper_on = _calculate_price_diff(
        amazon_result.get("price", ""),
        flipkart_result.get("price", ""),
    )

    amazon_resp = AmazonResponse(
        asin=amazon_result["asin"],
        price=amazon_result.get("price", ""),
        mrp=amazon_result.get("mrp"),
        rating=amazon_result.get("rating"),
        rating_count=amazon_result.get("rating_count"),
        rank_raw=amazon_result.get("rank_raw"),
        rank_value=amazon_result.get("rank_value"),
        rank_category=amazon_result.get("rank_category"),
        parent_node=amazon_result.get("parent_node"),
        child_node=amazon_result.get("child_node"),
        category_path=amazon_result.get("category_path"),
        status=amazon_result["status"],
        url=amazon_result["url"],
        checked_at=amazon_result["checked_at"],
    )

    flipkart_resp = FlipkartResponse(
        fsn=flipkart_result["fsn"],
        price=flipkart_result.get("price", ""),
        mrp=flipkart_result.get("mrp"),
        discount=flipkart_result.get("discount"),
        rating=flipkart_result.get("rating"),
        rating_count=flipkart_result.get("rating_count"),
        status=flipkart_result["status"],
        url=flipkart_result["url"],
        resolved_url=flipkart_result.get("resolved_url"),
        checked_at=flipkart_result["checked_at"],
    )

    return BothResponse(
        asin=body.asin,
        fsn=body.fsn,
        amazon=amazon_resp,
        flipkart=flipkart_resp,
        price_diff=price_diff,
        cheaper_on=cheaper_on,
    )


def _parse_price_to_float(price_str: str) -> float | None:
    """Extract numeric value from price string like '₹8,999'."""
    if not price_str:
        return None
    # Remove ₹ symbol, commas, and whitespace
    cleaned = re.sub(r"[₹,\s]", "", price_str)
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _calculate_price_diff(amazon_price: str, flipkart_price: str) -> tuple[str | None, str | None]:
    """Calculate price difference and determine cheaper platform."""
    a_val = _parse_price_to_float(amazon_price)
    f_val = _parse_price_to_float(flipkart_price)

    if a_val is None or f_val is None:
        return None, None

    diff = abs(a_val - f_val)
    diff_str = f"₹{diff:,.0f}"

    if a_val < f_val:
        return diff_str, "amazon"
    elif f_val < a_val:
        return diff_str, "flipkart"
    else:
        return "₹0", "same"
