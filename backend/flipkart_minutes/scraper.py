import os
import aiohttp
import asyncio
import logging
import re
import json
from typing import List, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def _error_result(item_id: str, city: str, url: str, msg: str = "error") -> dict:
    return {
        "product_id": item_id,
        "city": city,
        "title": None,
        "price": None,
        "mrp": None,
        "status": msg,
        "is_sold_out": False,
        "url": url,
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "error_message": msg,
    }

async def fetch_flipkart_minutes_data(
    item_id: str,
    lat: float,
    lon: float,
    pincode: str = None,
    city: str = "",
    browser: Any = None,
    proxy_manager: Any = None,
) -> dict:
    """Fetch Flipkart Minutes data using direct HTTP requests with cookies."""
    from dotenv import load_dotenv
    load_dotenv()
    
    product_url = f"https://www.flipkart.com/product/p/itme?pid={item_id}&marketplace=HYPERLOCAL"
    now = datetime.now(timezone.utc).astimezone().isoformat()
    
    cookie_string = os.environ.get("FLIPKART_MINUTES_COOKIES", "")
    if not cookie_string:
        logger.error("[FlipkartMinutes] FLIPKART_MINUTES_COOKIES not found in .env")
        return _error_result(item_id, city, product_url, "missing_cookies")
        
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": cookie_string,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(product_url, headers=headers, timeout=15) as response:
                if response.status != 200:
                    logger.warning(f"[FlipkartMinutes] HTTP {response.status} for {item_id}")
                    return _error_result(item_id, city, product_url, f"http_{response.status}")
                
                html = await response.text()
                
                # Safer and more optimized JSON-LD extraction
                price = None
                mrp = None
                
                # Find all JSON-LD blocks
                for match in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
                    try:
                        data = json.loads(match.group(1))
                        # The schema could be a list or a dict
                        if isinstance(data, list):
                            items = data
                        else:
                            items = [data]
                            
                        for item in items:
                            if item.get("@type") == "Product" and "offers" in item:
                                offers = item["offers"]
                                if isinstance(offers, dict):
                                    if "price" in offers:
                                        price = float(offers["price"])
                                    if "highPrice" in offers or "price" in offers:
                                        mrp = float(offers.get("highPrice", price))
                    except json.JSONDecodeError:
                        continue
                        
                if price is None:
                    # Fallback to general regex if JSON-LD parsing didn't find the product
                    price_match = re.search(r'"price":\s*([0-9.]+)', html)
                    mrp_match = re.search(r'"mrp":\s*([0-9.]+)', html)
                    if price_match:
                        price = float(price_match.group(1))
                        mrp = float(mrp_match.group(1)) if mrp_match else price
                
                if price is None:
                    logger.info(f"[FlipkartMinutes] No price found in HTML for {item_id}")
                    return _error_result(item_id, city, product_url, "data_not_found")
                
                # Simple title extraction
                import html as html_lib
                title = "Unknown Product"
                title_match = re.search(r'<title>(.*?)</title>', html)
                if title_match:
                    seo_title = html_lib.unescape(title_match.group(1))
                    t = seo_title.split(" Price in India")[0].strip()
                    if t and t != seo_title:
                        title = t
                    else:
                        t = seo_title.split(" - Buy ")[0].strip()
                        if t and t != seo_title:
                            title = t
                
                # Check stock
                is_sold_out = "Sold Out" in html or "Currently Unavailable" in html
                
                return {
                    "product_id": item_id,
                    "city": city,
                    "title": title,
                    "price": price,
                    "mrp": mrp,
                    "status": "available" if not is_sold_out else "out_of_stock",
                    "is_sold_out": is_sold_out,
                    "url": product_url,
                    "checked_at": now,
                    "error_message": None,
                }
                
    except Exception as e:
        logger.error(f"[FlipkartMinutes] Error scraping {item_id}: {e}")
        return _error_result(item_id, city, product_url, str(e))
