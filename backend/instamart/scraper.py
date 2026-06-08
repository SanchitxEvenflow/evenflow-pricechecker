"""
instamart/scraper.py
Playwright headful scraper for Instamart to bypass strict AWS WAF limits.
Extracts pricing from the DOM's embedded JSON state.
"""

import logging
import json
import re
import threading
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

from proxy.manager import ProxyManager

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_instamart_lock = threading.Lock()

def fetch_instamart_data(
    item_id: str,
    pincode: str,
    lat: float,
    lon: float,
    city: str,
    store_id: str,
    proxy_manager: ProxyManager | None = None,
) -> dict:
    product_url = f"https://www.swiggy.com/instamart/item/{item_id}"
    now = datetime.now(IST).isoformat()

    def _error_result(msg: str = "error") -> dict:
        return {
            "product_id": item_id,
            "city": city,
            "title": None,
            "price": None,
            "mrp": None,
            "status": "error",
            "is_sold_out": False,
            "url": product_url,
            "checked_at": now,
            "error_message": msg,
        }

    if store_id == "TODO" or not store_id:
        print(f"[Instamart] {city}: SKIPPED -- store_id not configured in locations.py")
        return _error_result("missing_store_id")

    with _instamart_lock:
        print(f"[Instamart] {city}: ACQUIRED LOCK, scraping item={item_id}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                
                # Inject the cookies for the target city
                context.add_cookies([
                    {"name": "lat", "value": str(lat), "domain": ".swiggy.com", "path": "/"},
                    {"name": "lng", "value": str(lon), "domain": ".swiggy.com", "path": "/"},
                    {"name": "storeId", "value": str(store_id), "domain": ".swiggy.com", "path": "/"}
                ])
                
                page = context.new_page()
                
                # Navigate to the product page. domcontentloaded is much faster than networkidle
                page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
                
                content = page.content()
                browser.close()
                

                # Find all script tags
                scripts = re.findall(r'<script.*?>(.*?)</script>', content, re.DOTALL)
                target_script = None
                for s in scripts:
                    if item_id in s and 'window.___INITIAL_STATE___' in s:
                        target_script = s
                        break
                        
                if not target_script:
                    print(f"[Instamart] {city}: Embedded state script not found")
                    return _error_result("state_script_not_found")
                    
                match = re.search(r'(\{.*\})', target_script)
                if not match:
                    print(f"[Instamart] {city}: Failed to regex JSON from script")
                    return _error_result("json_regex_failed")
                    
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    print(f"[Instamart] {city}: Invalid JSON decode")
                    return _error_result("invalid_json")
                    
                def find_items(obj, tgt_id):
                    results = []
                    if isinstance(obj, dict):
                        if obj.get('productId') == tgt_id:
                            results.append(obj)
                        for k, v in obj.items():
                            results.extend(find_items(v, tgt_id))
                    elif isinstance(obj, list):
                        for item in obj:
                            results.extend(find_items(item, tgt_id))
                    return results

                items = find_items(data, item_id)
                if not items:
                    print(f"[Instamart] {city}: item_not_found_in_state")
                    return _error_result("item_not_found_in_state")

                v = items[0]
                
                title = v.get("displayName", "Unknown Product")
                
                if "variations" in v and v["variations"]:
                    v = v["variations"][0]
                    title = v.get("displayName", title)
                    
                price_obj = v.get("price", {})
                price = None
                mrp = None
                is_sold_out = False
                status = "error"
                
                if price_obj:
                    o_price = price_obj.get("offerPrice", {}).get("units")
                    if o_price:
                        price = float(o_price)
                    m_price = price_obj.get("mrp", {}).get("units")
                    if m_price:
                        mrp = float(m_price)
                        
                inventory = v.get("inventory", {})
                if not inventory.get("inStock", False):
                    is_sold_out = True
                    status = "out_of_stock"
                else:
                    status = "available"
                    
                if not mrp and price:
                    mrp = price

                if price is None and not is_sold_out:
                    print(f"[Instamart] {city}: extraction failed (no price, not sold out)")
                    return _error_result("extraction_failed")

                print(f"[Instamart] {city}: OK -- {title} = Rs.{price} (MRP Rs.{mrp})")

                return {
                    "product_id": item_id,
                    "city": city,
                    "title": title,
                    "price": price,
                    "mrp": mrp,
                    "status": status,
                    "is_sold_out": is_sold_out,
                    "url": product_url,
                    "checked_at": now,
                }

        except Exception as e:
            logger.error("Unexpected error for item_id=%s: %s", item_id, e)
            print(f"[Instamart] {city}: UNEXPECTED ERROR: {e}")
            return _error_result(f"unexpected: {e}")
