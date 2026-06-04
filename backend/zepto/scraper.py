"""
zepto/scraper.py
HTTP Client using curl_cffi for Zepto's BFF API.
Mirrors the blinkit scraper structure: uses proxy manager, retry logic, and fallback.
"""

import logging
import os
from datetime import datetime, timezone, timedelta

from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError

from proxy.manager import ProxyManager

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# ── Config ──────────────────────────────────────────────────────────────────

ZEPTO_BFF_URL = os.getenv("ZEPTO_BFF_URL", "https://bff-gateway.zepto.com")

BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": "https://www.zeptonow.com",
    "Referer": "https://www.zeptonow.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Sec-Ch-Ua": '"Chromium";v="110", "Not A(Brand";v="24", "Google Chrome";v="110"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}

# ── Extraction Helpers ──────────────────────────────────────────────────────

def _extract_zepto_product(json_data: dict) -> dict:
    """
    Extract product details from Zepto's JSON response.
    This is a best-effort parse based on typical e-commerce app structures.
    """
    # Placeholder for actual Zepto extraction logic.
    # We will search the JSON tree for common keys.
    product = {}
    
    # Simple recursive search for known keys
    def _search_dict(d, keys):
        if not isinstance(d, dict):
            return None
        for k in keys:
            if k in d:
                return d[k]
        for v in d.values():
            if isinstance(v, (dict, list)):
                res = _search_dict(v, keys) if isinstance(v, dict) else next((_search_dict(i, keys) for i in v if isinstance(i, (dict, list))), None)
                if res is not None:
                    return res
        return None

    # Try to find common keys
    title = _search_dict(json_data, ["name", "title", "product_name"])
    price = _search_dict(json_data, ["selling_price", "discounted_price", "price"])
    mrp = _search_dict(json_data, ["mrp", "original_price", "marked_price"])
    stock = _search_dict(json_data, ["in_stock", "is_in_stock", "available_quantity"])
    
    # If not found using simple search, set defaults
    if price is not None:
        try:
            price = float(price) / 100 if price > 10000 else float(price) # Sometimes prices are in paise
        except (ValueError, TypeError):
            price = None
    if mrp is not None:
        try:
            mrp = float(mrp) / 100 if mrp > 10000 else float(mrp)
        except (ValueError, TypeError):
            mrp = None

    status = "available" if stock else "out_of_stock"
    if stock is None:
        status = "available" # Default to available if we can't find stock status

    return {
        "title": title or "Unknown Product",
        "price": price,
        "mrp": mrp,
        "status": status,
        "is_sold_out": status == "out_of_stock",
    }


# ── Main fetch function ────────────────────────────────────────────────────

def fetch_zepto_data(
    item_id: str,
    pincode: str,
    lat: float,
    lon: float,
    city: str,
    proxy_manager: ProxyManager | None = None,
) -> dict:
    """
    Fetch product data from Zepto.
    
    Retries up to min(5, pool_size) proxies on block/error, then falls back to
    a direct connection.
    
    This is a synchronous function (curl_cffi).
    """
    product_url = f"https://www.zeptonow.com/pn/product/{item_id}"
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

    logger.info("Fetching Zepto data for item_id=%s, city=%s (%s, %s)", item_id, city, lat, lon)

    max_proxy_attempts = min(5, len(proxy_manager.active_pool) if proxy_manager else 0)

    for attempt in range(max_proxy_attempts + 1):  # +1 = direct-connection fallback
        proxy = None
        if attempt < max_proxy_attempts and proxy_manager:
            proxy = proxy_manager.get_proxy()
        else:
            logger.info("All proxies exhausted — trying direct connection for item_id=%s", item_id)

        proxies = {"http": proxy, "https": proxy} if proxy else None
        session = requests.Session(impersonate="chrome110", proxies=proxies)

        try:
            # Phase 1: Resolve Coordinates to Store ID
            logger.info("Phase 1: Resolving store location (attempt %d/%d) for lat=%s, lon=%s",
                        attempt + 1, max_proxy_attempts + 1, lat, lon)
            
            loc_url = f"{ZEPTO_BFF_URL}/api/v1/maps/place/location?latitude={lat}&longitude={lon}"
            loc_response = session.get(loc_url, headers=BROWSER_HEADERS, timeout=15)
            
            if loc_response.status_code in (401, 403):
                logger.warning("Blocked (HTTP %d) on Phase 1 for item_id=%s — rotating proxy", loc_response.status_code, item_id)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result(f"blocked_{loc_response.status_code}")

            if loc_response.status_code != 200:
                logger.error("Zepto location API returned status %d", loc_response.status_code)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result(f"http_{loc_response.status_code}")

            loc_data = loc_response.json()
            # Extract store_id from the response (assuming it's in storeId or store_id key)
            store_id = None
            if "storeId" in loc_data:
                store_id = loc_data["storeId"]
            elif "store_id" in loc_data:
                store_id = loc_data["store_id"]
            elif "data" in loc_data and "storeId" in loc_data["data"]:
                store_id = loc_data["data"]["storeId"]
                
            if not store_id:
                # If we still can't find it, we'll try to proceed without it or fail gracefully
                logger.warning("Could not find store_id in Zepto location response")
                return _error_result("missing_store_id")

            logger.info("Resolved store_id=%s for city=%s", store_id, city)

            # Phase 2: Fetch Product Data using Store ID
            # Inject session state as requested: Cookie: latitude=X; longitude=Y; store_id=Z
            cookie_string = f"latitude={lat}; longitude={lon}; store_id={store_id};"
            headers = BROWSER_HEADERS.copy()
            headers["Cookie"] = cookie_string

            # We use a best-guess URL based on user info "get_page?store_id=..."
            prod_url = f"{ZEPTO_BFF_URL}/api/v1/config/layout/?store_id={store_id}&page_type=PRODUCT_DETAIL&product_id={item_id}"
            
            logger.info("Phase 2: Fetch product details for item_id=%s", item_id)
            response = session.get(prod_url, headers=headers, timeout=15)

            if response.status_code in (401, 403):
                logger.warning("Blocked (HTTP %d) on Phase 2 for item_id=%s", response.status_code, item_id)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result(f"blocked_{response.status_code}")

            if response.status_code == 404:
                logger.warning("Item %s not found/unserviceable", item_id)
                if proxy_manager:
                    proxy_manager.report_success(proxy)
                return {
                    "product_id": item_id,
                    "city": city,
                    "title": "Not Found",
                    "price": None,
                    "mrp": None,
                    "status": "not_found",
                    "is_sold_out": True,
                    "url": product_url,
                    "checked_at": now,
                }

            if response.status_code != 200:
                logger.error("Zepto product API returned status %d for item_id=%s", response.status_code, item_id)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result(f"http_{response.status_code}")

            json_data = response.json()
            
            # Extract product data
            product = _extract_zepto_product(json_data)

            if proxy_manager:
                proxy_manager.report_success(proxy)

            return {
                "product_id": item_id,
                "city": city,
                "title": product["title"],
                "price": product["price"],
                "mrp": product["mrp"],
                "status": product["status"],
                "is_sold_out": product["is_sold_out"],
                "url": product_url,
                "checked_at": now,
            }

        except (RequestsError, TimeoutError) as e:
            logger.error("Network/timeout error on attempt %d for item_id=%s: %s", attempt + 1, item_id, e)
            if proxy_manager:
                proxy_manager.report_failure(proxy)
            if attempt < max_proxy_attempts:
                continue
            return _error_result(f"network_error: {e}")

        except ValueError as e:
            logger.error("JSON/extraction error on attempt %d for item_id=%s: %s", attempt + 1, item_id, e)
            if "response" in dir():
                text = response.text.lower()
                if "cloudflare" in text or "<html" in text:
                    logger.error("Cloudflare challenge detected — rotate proxies")
                    if proxy_manager:
                        proxy_manager.report_failure(proxy)
                    if attempt < max_proxy_attempts:
                        continue
            return _error_result(f"extraction_error: {e}")

        except Exception as e:
            logger.error("Unexpected error on attempt %d for item_id=%s: %s", attempt + 1, item_id, e)
            if proxy_manager:
                proxy_manager.report_failure(proxy)
            if attempt < max_proxy_attempts:
                continue
            return _error_result(f"unexpected: {e}")

        finally:
            session.close()

    return _error_result("max_retries_exceeded")
