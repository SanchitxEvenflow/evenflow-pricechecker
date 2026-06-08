"""
instamart/scraper.py
Async Playwright scraper for Instamart (Swiggy).
Mirrors the amazon/flipkart scraper architecture:
  - Reuses the global shared Playwright browser (launched at app startup)
  - Creates a lightweight per-request browser context (never launches Chromium itself)
  - Proxy rotation retry loop identical to amazon/flipkart
  - Reports proxy success/failure to ProxyManager
  - Falls back to a direct connection after exhausting the proxy pool
"""

import logging
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

# pyrefly: ignore [missing-import]
from playwright.async_api import Browser

from proxy.manager import ProxyManager

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Stealth init script — identical to amazon/flipkart
STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });
window.chrome = { runtime: {} };
"""


def _parse_proxy(proxy_url: str) -> dict:
    """Parse proxy URL into Playwright's proxy format dict."""
    parsed = urlparse(proxy_url)
    result: dict = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        result["username"] = parsed.username
    if parsed.password:
        result["password"] = parsed.password
    return result


async def _safe_close_context(context) -> None:
    """Safely close a Playwright browser context — never leak."""
    if context:
        try:
            await context.close()
        except Exception:
            pass


def _find_items(obj, tgt_id: str) -> list:
    """Recursively walk a parsed JSON object to find nodes matching productId."""
    results = []
    if isinstance(obj, dict):
        if obj.get("productId") == tgt_id:
            results.append(obj)
        for v in obj.values():
            results.extend(_find_items(v, tgt_id))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_find_items(item, tgt_id))
    return results


async def fetch_instamart_data(
    item_id: str,
    pincode: str,
    lat: float,
    lon: float,
    city: str,
    store_id: str,
    browser: Browser,
    proxy_manager: ProxyManager | None = None,
) -> dict:
    """
    Fetch product data from Instamart (Swiggy) using the shared Playwright browser.

    Tries up to min(3, pool_size) proxies on block/error, then falls back to a
    direct connection — identical retry logic to amazon/flipkart scrapers.

    Cookies (lat, lng, storeId) are injected per context so that Swiggy's CDN
    serves the correct city-specific inventory and pricing.

    Returns a dict with keys:
        product_id, city, title, price, mrp, status, is_sold_out, url, checked_at
    """
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
        logger.warning("[Instamart] %s: SKIPPED — store_id not configured in locations.py", city)
        return _error_result("missing_store_id")

    max_proxy_attempts = min(3, len(proxy_manager.active_pool) if proxy_manager else 0)
    context = None

    for attempt in range(max_proxy_attempts + 1):  # +1 = direct-connection fallback
        proxy = None
        if attempt < max_proxy_attempts and proxy_manager:
            proxy = proxy_manager.get_proxy()
        else:
            logger.info("[Instamart] %s: trying direct connection (attempt %d)", city, attempt + 1)

        context_opts: dict = {
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
        }
        if proxy:
            context_opts["proxy"] = _parse_proxy(proxy)

        try:
            logger.info(
                "[Instamart] %s: attempt %d/%d — item=%s proxy=%s",
                city, attempt + 1, max_proxy_attempts + 1, item_id, proxy,
            )

            context = await browser.new_context(**context_opts)
            await context.add_init_script(STEALTH_SCRIPT)

            # Inject location cookies so Swiggy routes to the right city/store
            await context.add_cookies([
                {"name": "lat",     "value": str(lat),      "domain": ".swiggy.com", "path": "/"},
                {"name": "lng",     "value": str(lon),      "domain": ".swiggy.com", "path": "/"},
                {"name": "storeId", "value": str(store_id), "domain": ".swiggy.com", "path": "/"},
            ])

            page = await context.new_page()

            # domcontentloaded is much faster than networkidle for JSON-in-script extraction
            await page.goto(product_url, wait_until="domcontentloaded", timeout=60000)

            content = await page.content()

            # Check for bot challenge page
            lower = content.lower()
            if "captcha" in lower or "robot check" in lower or "access denied" in lower:
                logger.warning("[Instamart] %s: bot challenge on attempt %d", city, attempt + 1)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                await _safe_close_context(context)
                context = None
                if attempt < max_proxy_attempts:
                    continue
                return _error_result("blocked")

            # ── Extract embedded JSON state ────────────────────────────────
            scripts = re.findall(r"<script.*?>(.*?)</script>", content, re.DOTALL)
            target_script = None
            for s in scripts:
                if item_id in s and "window.___INITIAL_STATE___" in s:
                    target_script = s
                    break

            if not target_script:
                logger.warning("[Instamart] %s: embedded state script not found", city)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                await _safe_close_context(context)
                context = None
                if attempt < max_proxy_attempts:
                    continue
                return _error_result("state_script_not_found")

            match = re.search(r"window\.___INITIAL_STATE___\s*=\s*(.*?);\s*(?:window\.|var\s|let\s|const\s)", target_script, re.DOTALL)
            if not match:
                logger.warning("[Instamart] %s: failed to regex JSON from script", city)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                await _safe_close_context(context)
                context = None
                if attempt < max_proxy_attempts:
                    continue
                return _error_result("json_regex_failed")

            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                logger.warning("[Instamart] %s: invalid JSON in embedded state", city)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                await _safe_close_context(context)
                context = None
                if attempt < max_proxy_attempts:
                    continue
                return _error_result("invalid_json")

            # ── Extract product node from state tree ───────────────────────
            items = _find_items(data, item_id)
            if not items:
                logger.warning("[Instamart] %s: item_not_found_in_state", city)
                if proxy_manager:
                    proxy_manager.report_success(proxy)
                await _safe_close_context(context)
                context = None
                return _error_result("item_not_found_in_state")

            v = items[0]
            title = v.get("displayName", "Unknown Product")

            if v.get("variations"):
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
                logger.warning("[Instamart] %s: extraction failed (no price, not sold out)", city)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                await _safe_close_context(context)
                context = None
                if attempt < max_proxy_attempts:
                    continue
                return _error_result("extraction_failed")

            logger.info("[Instamart] %s: OK — %s = Rs.%s (MRP Rs.%s)", city, title, price, mrp)
            if proxy_manager:
                proxy_manager.report_success(proxy)

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
            logger.error(
                "[Instamart] %s: unexpected error on attempt %d — %s",
                city, attempt + 1, e,
            )
            if proxy_manager:
                proxy_manager.report_failure(proxy)
            await _safe_close_context(context)
            context = None
            if attempt < max_proxy_attempts:
                continue
            return _error_result(f"unexpected: {e}")

        finally:
            await _safe_close_context(context)
            context = None

    return _error_result("max_retries_exceeded")
