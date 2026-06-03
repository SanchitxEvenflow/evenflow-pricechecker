"""
blinkit/scraper.py
HTTP Client using curl_cffi for Blinkit's layout/product API.
Ported from blinkitscraper/client.py — adapted for price-checker conventions.

Key differences from the standalone scraper:
  - Accepts proxy as a string param (from ProxyManager) instead of internal get_random_proxy()
  - Returns a plain dict (not Pydantic model) matching price-checker conventions
  - No tenacity @retry decorator — caller handles retries
  - Status values: "available", "out_of_stock", "unserviceable", "error"
"""

import logging
import os
import re
import threading
from datetime import datetime, timezone, timedelta

from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# ── Config ──────────────────────────────────────────────────────────────────

BLINKIT_BASE_URL = os.getenv("BLINKIT_BASE_URL", "https://blinkit.com/v1/layout/product")
BLINKIT_DEVICE_ID = os.getenv("BLINKIT_DEVICE_ID", "c834d3ca-5f99-48ed-8ff2-b62759933bcf")

BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="110", "Not A(Brand";v="24", "Google Chrome";v="110"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Origin": "https://blinkit.com",
    "Referer": "https://blinkit.com/",
}


# ── Price text parser ───────────────────────────────────────────────────────

def _parse_price_text(raw: str) -> float:
    """Extract numeric price from Blinkit's formatted string (e.g. '₹350' → 350.0)."""
    if not raw:
        raise ValueError("Empty price string")
    match = re.search(r"₹\s*([\d.,]+)", raw)
    if match:
        return float(match.group(1).replace(",", ""))
    cleaned = re.sub(r"[^\d.,]", "", raw).replace(",", "")
    if not cleaned:
        raise ValueError(f"Could not extract numeric price from: '{raw}'")
    return float(cleaned)


# ── Layout JSON extraction ─────────────────────────────────────────────────

def _extract_product_from_layout(json_data: dict) -> dict:
    """
    Navigate Blinkit's nested layout JSON tree to extract product data.

    Handles two API response formats:
      Format A (older): sticky.footer_snippet_models[0].snippet.data
      Format B (newer): sticky.footer_snippets[0].data

    Returns dict with keys: title, price, mrp, status, is_sold_out
    """
    response_obj = json_data.get("response")
    if response_obj is None:
        raise ValueError(f"Missing 'response' in API payload. Keys: {list(json_data.keys())}")

    page_components = response_obj.get("page_level_components")
    if page_components is None:
        raise ValueError(f"Missing 'page_level_components'. Keys: {list(response_obj.keys())}")

    sticky = page_components.get("sticky")
    if sticky is None:
        raise ValueError(f"Missing 'sticky'. Keys: {list(page_components.keys())}")

    # Try both key names: footer_snippet_models (old) and footer_snippets (new)
    footer_list = sticky.get("footer_snippet_models") or sticky.get("footer_snippets")
    if not footer_list or not isinstance(footer_list, list) or len(footer_list) == 0:
        raise ValueError(f"Missing footer snippets. Sticky keys: {list(sticky.keys())}")

    # Extract data_block: handle both formats
    first_item = footer_list[0]
    if "snippet" in first_item:
        data_block = first_item["snippet"].get("data")
        tracking_block = first_item["snippet"].get("tracking", {})
    elif "data" in first_item:
        data_block = first_item.get("data")
        tracking_block = first_item.get("tracking", {})
    else:
        raise ValueError(f"Cannot find 'data' or 'snippet' in footer item. Keys: {list(first_item.keys())}")

    if data_block is None:
        raise ValueError("data_block is None after footer extraction")

    # Extract from cart_item (most reliable for price/mrp/title)
    cart_item = None
    atc_actions = data_block.get("atc_actions_v2", {})
    if isinstance(atc_actions, dict):
        default_actions = atc_actions.get("default", [])
        if default_actions and isinstance(default_actions, list):
            for action in default_actions:
                if isinstance(action, dict) and "add_to_cart" in action:
                    cart_item = action["add_to_cart"].get("cart_item", {})
                    break

    if not cart_item:
        rfc_actions = data_block.get("rfc_actions_v2", {})
        if isinstance(rfc_actions, dict):
            default_actions = rfc_actions.get("default", [])
            if default_actions and isinstance(default_actions, list):
                for action in default_actions:
                    if isinstance(action, dict) and "remove_from_cart" in action:
                        cart_item = action["remove_from_cart"].get("cart_item", {})
                        break

    # Inventory/status
    is_sold_out = data_block.get("is_sold_out", False)
    product_state = data_block.get("product_state", "")
    inventory = data_block.get("inventory", 0)

    if is_sold_out or product_state == "out_of_stock" or inventory == 0:
        status = "out_of_stock"
    else:
        status = "available"

    # Title (priority: cart_item > tracking > snippets)
    title = None
    if cart_item:
        title = cart_item.get("product_name") or cart_item.get("display_name")
    if not title and tracking_block:
        widget_meta = tracking_block.get("widget_meta", {})
        title = widget_meta.get("widget_title")
    if not title:
        snippets = response_obj.get("snippets")
        if snippets and isinstance(snippets, list):
            for snip in snippets:
                snip_data = snip.get("data", {})
                title_obj = snip_data.get("title")
                if isinstance(title_obj, dict) and title_obj.get("text"):
                    candidate = title_obj["text"]
                    if len(candidate) > 10:
                        title = candidate
                        break

    # Prices (priority: cart_item numeric > text parsing)
    current_price = None
    mrp_value = None

    if cart_item:
        current_price = float(cart_item["price"]) if cart_item.get("price") else None
        mrp_value = float(cart_item["mrp"]) if cart_item.get("mrp") else None
    else:
        normal_price_obj = data_block.get("normal_price")
        mrp_obj = data_block.get("mrp")
        if normal_price_obj and isinstance(normal_price_obj, dict):
            try:
                current_price = _parse_price_text(normal_price_obj.get("text", ""))
            except ValueError:
                logger.warning("Could not parse normal_price text: '%s'", normal_price_obj.get("text"))
        if mrp_obj and isinstance(mrp_obj, dict):
            try:
                mrp_value = _parse_price_text(mrp_obj.get("text", ""))
            except ValueError:
                logger.warning("Could not parse mrp text: '%s'", mrp_obj.get("text"))

    logger.info("Extracted: '%s' | %s | ₹%s | MRP ₹%s | sold_out=%s", title, status, current_price, mrp_value, is_sold_out)

    return {
        "title": title,
        "price": current_price,
        "mrp": mrp_value,
        "status": status,
        "is_sold_out": is_sold_out,
    }


# ── Thread-local session management ────────────────────────────────────────

_thread_local = threading.local()


def _get_thread_session(proxy: str | None = None):
    """Get or create a thread-local curl_cffi session with Phase 1 handshake."""
    if not hasattr(_thread_local, "session"):
        proxies = {"http": proxy, "https": proxy} if proxy else None
        session = requests.Session(impersonate="chrome110", proxies=proxies)

        # Phase 1: Landing page handshake — warm up cookies
        logger.info("Phase 1: Session handshake with blinkit.com/robots.txt")
        try:
            landing = session.get("https://blinkit.com/robots.txt", headers=BROWSER_HEADERS, timeout=15)
            if landing.status_code != 200:
                logger.warning("Phase 1 landing returned status: %d", landing.status_code)
        except Exception as e:
            logger.warning("Phase 1 handshake failed: %s", e)

        _thread_local.session = session

    return _thread_local.session


def _clear_thread_session():
    """Close and discard the thread-local session (e.g. on network error for retry)."""
    if hasattr(_thread_local, "session"):
        try:
            _thread_local.session.close()
        except Exception:
            pass
        del _thread_local.session


# ── Main fetch function ────────────────────────────────────────────────────

def fetch_blinkit_data(
    item_id: str,
    pincode: str,
    lat: float,
    lon: float,
    city: str,
    proxy: str | None = None,
) -> dict:
    """
    Fetch product data from Blinkit's layout/product API.

    This is a synchronous function (curl_cffi). The caller must wrap it with
    asyncio.loop.run_in_executor() when used in async contexts.

    Returns a dict with keys:
        product_id, city, title, price, mrp, status, is_sold_out, url, checked_at
    """
    url = f"{BLINKIT_BASE_URL}/{item_id}"
    product_url = f"https://blinkit.com/pr/x/pr_{item_id}"
    now = datetime.now(IST).isoformat()

    # Error result template
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

    headers = {
        "Accept": "application/json, text/plain, */*",
        "app_client": "consumer_web",
        "Origin": "https://blinkit.com",
        "Referer": f"https://blinkit.com/pr/x/pr_{item_id}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "lat": str(lat),
        "lon": str(lon),
    }

    payload = {
        "pincode": str(pincode),
        "lat": float(lat),
        "lon": float(lon),
        "lng": float(lon),
        "layout_tabs": [],
    }

    logger.info("POSTing to Blinkit for item_id=%s, city=%s (%s, %s)", item_id, city, lat, lon)

    try:
        session = _get_thread_session(proxy)

        # Inject location cookies
        session.cookies.set("gr_1_lat", str(lat), domain=".blinkit.com", path="/")
        session.cookies.set("gr_1_lon", str(lon), domain=".blinkit.com", path="/")
        session.cookies.set("city", str(city), domain=".blinkit.com", path="/")
        session.cookies.set("gr_1_deviceId", str(BLINKIT_DEVICE_ID), domain=".blinkit.com", path="/")

        # Phase 2 intentionally skipped — /eta endpoint poisons session cookies
        # causing is_success=False for many items.

        # Phase 3: Layout POST request
        logger.info("Phase 3: POST layout for item_id=%s", item_id)
        response = session.post(url, headers=headers, json=payload, timeout=15)

        # Non-200 handling
        if response.status_code != 200:
            logger.error("Blinkit API returned status %d for item_id=%s", response.status_code, item_id)

            if response.status_code in (401, 403):
                logger.error("BLOCKED: Get a new BLINKIT_DEVICE_ID or rotate proxies")

            if response.status_code in (500, 502, 503, 504):
                logger.error("Upstream server error %d — returning error dict", response.status_code)
                return _error_result(f"upstream_{response.status_code}")

            return _error_result(f"http_{response.status_code}")

        json_data = response.json()

        # Handle is_success=False
        if json_data.get("is_success") is False:
            snippets = json_data.get("response", {}).get("snippets")
            if snippets is None:
                # Item is unserviceable at this pincode/dark store
                logger.warning("Item %s is unserviceable at pincode %s", item_id, pincode)
                return {
                    "product_id": item_id,
                    "city": city,
                    "title": f"Unserviceable at {city}",
                    "price": None,
                    "mrp": None,
                    "status": "unserviceable",
                    "is_sold_out": True,
                    "url": product_url,
                    "checked_at": now,
                }
            else:
                # is_success=False but snippets exist — unexpected
                logger.error("Blinkit rejected with non-null snippets: %s", response.text[:300])
                return _error_result("rejected_with_snippets")

        # Extract product data from nested layout tree
        product = _extract_product_from_layout(json_data)

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

    except RequestsError as e:
        logger.error("Network error for item_id=%s: %s", item_id, e)
        _clear_thread_session()
        return _error_result(f"network_error: {e}")

    except TimeoutError as e:
        logger.error("Timeout for item_id=%s: %s", item_id, e)
        _clear_thread_session()
        return _error_result(f"timeout: {e}")

    except ValueError as e:
        logger.error("JSON/extraction error for item_id=%s: %s", item_id, e)
        # Check for Cloudflare challenge
        if "response" in locals():
            text = response.text.lower()
            if "cloudflare" in text or "<html" in text:
                logger.error("Cloudflare challenge detected — rotate DEVICE_ID or proxies")
        return _error_result(f"extraction_error: {e}")

    except Exception as e:
        logger.error("Unexpected error for item_id=%s: %s", item_id, e)
        return _error_result(f"unexpected: {e}")
