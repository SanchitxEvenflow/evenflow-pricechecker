"""Instamart quick-commerce scraper.

Fetches product data from Swiggy Instamart BFF/widgets API.
"""

from __future__ import annotations

import logging
import os
import random
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import requests
from curl_cffi.requests.errors import RequestsError

from proxy.manager import ProxyManager

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

INSTAMART_PRODUCT_BASE_URL = "https://www.swiggy.com/instamart/item/{item_id}"
INSTAMART_WIDGETS_URL = (
    "https://www.swiggy.com/api/instamart/item/v2/{product_id}/widgets"
    "?storeId={store_id}&primaryStoreId={store_id}&secondaryStoreId="
)


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _to_rupees(maybe_paise_or_price: Any) -> float | None:
    if maybe_paise_or_price is None:
        return None
    try:
        # API might return numeric or string.
        v = float(maybe_paise_or_price)
        # Heuristic: paise are usually integers like 91000.
        if v.is_integer() and v > 1000:
            return round(v / 100.0, 2)
        return round(v, 2)
    except (ValueError, TypeError):
        return None


def _error_result(item_id: str, city: str, url: str, checked_at: str, status: str, msg: str | None = None) -> dict:
    return {
        "product_id": item_id,
        "city": city,
        "title": None,
        "price": None,
        "mrp": None,
        "status": status,
        "is_sold_out": status == "out_of_stock",
        "url": url,
        "checked_at": checked_at,
        "error_message": msg,
    }


def _build_headers(item_id: str, store_id: str, lat: float, lon: float, address: str, pincode: str | None) -> dict[str, str]:
    # Browser-like headers. Cookie/session values are carried via env vars.
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    cookie = os.getenv("INSTAMART_COOKIE", "")
    matcher = os.getenv("INSTAMART_MATCHER", "")

    # Volatile IDs.
    device_id = os.getenv("INSTAMART_DEVICE_ID") or str(uuid.uuid4())
    x_build_version = os.getenv("INSTAMART_BUILD_VERSION", "2.347.0")

    # Swiggy often expects a matcher param.
    # We put matcher and cookie behind env vars; we do NOT hardcode pasted full cookie strings in source.

    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": INSTAMART_PRODUCT_BASE_URL.format(item_id=item_id),
        "content-type": "application/json",
        "x-build-version": str(x_build_version),
        "x-device-id": str(device_id),
        # Some WAFs key off matcher header.
        "matcher": str(matcher),
        # location hints (custom headers may be ignored but help).
        "x-lat": str(lat),
        "x-lng": str(lon),
        "x-address": address,
    }

    if pincode:
        headers["x-pincode"] = str(pincode)

    if cookie:
        headers["cookie"] = cookie

    # Optional anti-bot session cookies.
    return headers


def fetch_instamart_data(
    item_id: str,
    lat: float,
    lon: float,
    city: str,
    store_id: str,
    address: str,
    pincode: str | None = None,
    proxy_manager: ProxyManager | None = None,
) -> dict:
    """Fetch Instamart widgets for a single city.

    Instamart scraping contract:
    - product url: https://www.swiggy.com/instamart/item/{product_id}
    - widgets api: /api/instamart/item/v2/{product_id}/widgets?storeId=...&primaryStoreId=...&secondaryStoreId=
    """

    checked_at = _now_iso()
    product_url = INSTAMART_PRODUCT_BASE_URL.format(item_id=item_id)

    if not store_id:
        return _error_result(item_id, city, product_url, checked_at, "unserviceable", "missing_store_id")

    headers = _build_headers(item_id, store_id, lat, lon, address, pincode)
    headers["Referer"] = f"https://www.swiggy.com/instamart/item/{item_id}"

    widgets_url = INSTAMART_WIDGETS_URL.format(product_id=item_id, store_id=store_id)

    max_proxy_attempts = min(
        int(os.getenv("INSTAMART_CONCURRENCY", "5")),
        len(proxy_manager.active_pool) if proxy_manager else 0,
        3,
    )

    def _parse_widgets(payload: dict[str, Any]) -> tuple[str | None, float | None, float | None, str, bool]:
        """Defensively search widgets payload for title/price/mrp/availability."""

        title: str | None = None
        price: float | None = None
        mrp: float | None = None
        is_sold_out: bool = False

        possible_title_keys = {"title", "productTitle", "name"}
        price_keys = {"price", "sellingPrice", "discountedSellingPrice", "superSaverSellingPrice"}
        mrp_keys = {"mrp", "listPrice"}
        sold_out_keys = {"isSoldOut", "outOfStock", "is_sold_out"}

        def walk(obj: Any):
            if isinstance(obj, dict):
                yield obj
                for v in obj.values():
                    yield from walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from walk(v)

        for d in walk(payload):
            if title is None:
                for k in possible_title_keys:
                    val = d.get(k)
                    if val:
                        title = str(val)
                        break

            if price is None:
                for k in price_keys:
                    if k in d and d.get(k) is not None:
                        price = _to_rupees(d.get(k))
                        break

            if mrp is None:
                for k in mrp_keys:
                    if k in d and d.get(k) is not None:
                        mrp = _to_rupees(d.get(k))
                        break

            for k in sold_out_keys:
                if k in d:
                    v = d.get(k)
                    if isinstance(v, str):
                        is_sold_out = v.lower() in ("true", "1", "yes")
                    else:
                        is_sold_out = bool(v)
                    break

        # Status mapping
        if is_sold_out:
            status = "out_of_stock"
        else:
            status = "available" if price is not None else "error"

        return title, price, mrp, status, is_sold_out

    for attempt in range(max_proxy_attempts + 1):
        proxy = None
        if attempt < max_proxy_attempts and proxy_manager:
            proxy = proxy_manager.get_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None

        session = requests.Session()
        try:
            delay_min = float(os.getenv("INSTAMART_DELAY_MIN", "1.0"))
            delay_max = float(os.getenv("INSTAMART_DELAY_MAX", "3.0"))
            if delay_max > 0:
                delay = random.uniform(delay_min, delay_max)
                if delay > 0.01:
                    import time
                    time.sleep(delay)

            resp = session.get(widgets_url, headers=headers, proxies=proxies, timeout=20)

            if resp.status_code == 404:
                if proxy_manager and proxy:
                    proxy_manager.report_success(proxy)
                return _error_result(item_id, city, product_url, checked_at, "not_found", "http_404")

            if resp.status_code in (401, 403, 429):
                if proxy_manager and proxy:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result(item_id, city, product_url, checked_at, "error", f"blocked_{resp.status_code}")

            if resp.status_code != 200:
                if proxy_manager and proxy:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result(item_id, city, product_url, checked_at, "error", f"http_{resp.status_code}")

            try:
                payload = resp.json()
            except Exception as e:
                if proxy_manager and proxy:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result(item_id, city, product_url, checked_at, "error", f"json_parse_error: {e}")

            title, price, mrp, status, is_sold_out = _parse_widgets(payload)

            if status == "available":
                return {
                    "product_id": item_id,
                    "city": city,
                    "title": title,
                    "price": price,
                    "mrp": mrp,
                    "status": "available",
                    "is_sold_out": False,
                    "url": product_url,
                    "checked_at": checked_at,
                    "error_message": None,
                }

            if status == "out_of_stock":
                return {
                    "product_id": item_id,
                    "city": city,
                    "title": title,
                    "price": None,
                    "mrp": mrp,
                    "status": "out_of_stock",
                    "is_sold_out": True,
                    "url": product_url,
                    "checked_at": checked_at,
                    "error_message": None,
                }

            # Not found-ish / parse failures
            if proxy_manager and proxy:
                proxy_manager.report_success(proxy)
            return _error_result(item_id, city, product_url, checked_at, "error", "parse_failed_or_unexpected")

        except (RequestsError, TimeoutError) as e:
            if proxy_manager and proxy:
                proxy_manager.report_failure(proxy)
            if attempt < max_proxy_attempts:
                continue
            return _error_result(item_id, city, product_url, checked_at, "error", f"network_error: {e}")
        except Exception as e:
            if proxy_manager and proxy:
                proxy_manager.report_failure(proxy)
            if attempt < max_proxy_attempts:
                continue
            return _error_result(item_id, city, product_url, checked_at, "error", f"unexpected: {e}")
        finally:
            try:
                session.close()
            except Exception:
                pass

    return _error_result(item_id, city, product_url, checked_at, "error", "max_retries_exceeded")


