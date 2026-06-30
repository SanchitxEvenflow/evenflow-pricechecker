"""
instamart/scraper.py
Swiggy Instamart price scraper — direct HTTP via curl_cffi, no Playwright.

Fetches the SSR product page and extracts product data from the embedded
window.___INITIAL_STATE___ JSON.  Uses curl_cffi with TLS fingerprint
impersonation (chrome124) to bypass anti-bot checks.

Architecture mirrors zepto/scraper.py:
  - Synchronous (curl_cffi) — caller wraps with run_in_executor
  - Proxy rotation retry loop with ProxyManager
  - Per-request Session for thread safety
"""

import json
import logging
import re
from datetime import datetime, timezone, timedelta

from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError

from proxy.manager import ProxyManager

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "User-Agent": _CHROME_UA,
}


# ── SSR state extraction ───────────────────────────────────────────────────

_ASSIGN_RE = re.compile(r"window\.___INITIAL_STATE___\s*=\s*")


def _extract_initial_state(script: str) -> dict:
    """
    Brace-aware extraction of window.___INITIAL_STATE___ from a script block.

    Uses regex only to locate the assignment, then manually tracks open/close
    braces and brackets (respecting strings and escapes) to find the exact end
    of the JSON payload.  This is robust to minification changes and arbitrary
    JS that follows the assignment.
    """
    m = _ASSIGN_RE.search(script)
    if not m:
        raise ValueError("initial_state_assignment_not_found")

    i = m.end()
    n = len(script)

    while i < n and script[i].isspace():
        i += 1

    if i >= n or script[i] not in "{[":
        raise ValueError("initial_state_not_json_like")

    start = i
    stack = [script[i]]
    i += 1

    in_string = False
    quote = ""
    escaped = False

    while i < n:
        ch = script[i]

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_string = False
        else:
            if ch in ('"', "'"):
                in_string = True
                quote = ch
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if not stack:
                    raise ValueError("unexpected_closing_brace")
                opening = stack.pop()
                if (opening, ch) not in {("{", "}"), ("[", "]")}:
                    raise ValueError("mismatched_braces")
                if not stack:
                    payload = script[start : i + 1]
                    return json.loads(payload)

        i += 1

    raise ValueError("initial_state_unterminated")


# ── JSON tree helpers ──────────────────────────────────────────────────────


def _find_items(obj, tgt_id: str) -> list:
    """Recursively walk parsed JSON to find nodes where productId == tgt_id."""
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


def _extract_price_and_stock(item: dict, target_variant_name: str | None = None) -> dict:
    """
    Extract price, mrp, title, and stock from a product node in the
    ___INITIAL_STATE___ tree.  Handles variant selection.
    """
    title = item.get("displayName", "Unknown Product")

    # ── Variant selection (cheapest by default, or match target name) ──
    v = item
    if item.get("variations"):
        variations = list(item["variations"])  # copy — avoid mutating state tree

        def _get_price(var):
            p = var.get("price", {})
            val = (
                p.get("offerPrice", {}).get("units")
                or p.get("mrp", {}).get("units")
                or float("inf")
            )
            return float(val)

        variations.sort(key=_get_price)

        selected_var = variations[0]
        if target_variant_name:
            for var in variations:
                if var.get("displayName") == target_variant_name:
                    selected_var = var
                    break

        v = selected_var
        title = v.get("displayName", title)

    # ── Price extraction ──
    price_obj = v.get("price", {})
    price = None
    mrp = None

    if price_obj:
        o_price = price_obj.get("offerPrice", {}).get("units")
        if o_price is not None:
            price = float(o_price)
        m_price = price_obj.get("mrp", {}).get("units")
        if m_price is not None:
            mrp = float(m_price)

    if mrp is None and price is not None:
        mrp = price

    # ── Stock status ──
    inventory = v.get("inventory", {})
    is_sold_out = not inventory.get("inStock", False)
    status = "out_of_stock" if is_sold_out else "available"

    return {
        "title": title,
        "price": price,
        "mrp": mrp,
        "status": status,
        "is_sold_out": is_sold_out,
    }


# ── Main fetch function ────────────────────────────────────────────────────


def fetch_instamart_data(
    item_id: str,
    lat: float,
    lon: float,
    city: str,
    store_id: str,
    proxy_manager: ProxyManager | None = None,
    target_variant_name: str | None = None,
) -> dict:
    """
    Fetch product data from Swiggy Instamart via direct HTTP + SSR parsing.

    Sends a GET request to the product page with location cookies injected,
    then extracts the embedded ___INITIAL_STATE___ JSON to pull price data.

    This is a synchronous function (curl_cffi).  The caller must wrap it with
    asyncio.loop.run_in_executor() when used in async contexts.

    Returns a dict with keys:
        product_id, city, title, price, mrp, status, is_sold_out, url,
        checked_at, error_message
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

    if not store_id or store_id == "TODO":
        logger.warning("[Instamart] %s: SKIPPED — store_id not configured", city)
        return _error_result("missing_store_id")

    max_proxy_attempts = min(3, len(proxy_manager.active_pool) if proxy_manager else 0)

    for attempt in range(max_proxy_attempts + 1):  # +1 = direct-connection fallback
        proxy = None
        if attempt < max_proxy_attempts and proxy_manager:
            proxy = proxy_manager.get_proxy()
        else:
            logger.info("[Instamart] %s: trying direct connection (attempt %d)", city, attempt + 1)

        proxies = {"http": proxy, "https": proxy} if proxy else None
        session = requests.Session(impersonate="chrome124", proxies=proxies, verify=False)

        try:
            # Inject location cookies so Swiggy routes to the correct city/store
            session.cookies.set("lat", str(lat), domain=".swiggy.com", path="/")
            session.cookies.set("lng", str(lon), domain=".swiggy.com", path="/")
            session.cookies.set("storeId", str(store_id), domain=".swiggy.com", path="/")

            logger.info(
                "[Instamart] %s: GET %s (attempt %d/%d, proxy=%s)",
                city, product_url[:80], attempt + 1, max_proxy_attempts + 1, proxy,
            )
            response = session.get(product_url, headers=_BASE_HEADERS, timeout=20)
            content = response.text
            lower = content.lower()

            # ── Bot / error page detection ─────────────────────────────────
            if response.status_code in (401, 403, 429):
                logger.warning(
                    "[Instamart] %s: blocked (HTTP %d) on attempt %d",
                    city, response.status_code, attempt + 1,
                )
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result(f"blocked_{response.status_code}")

            if any(x in lower for x in ["captcha", "robot check", "access denied"]):
                logger.warning("[Instamart] %s: bot challenge on attempt %d", city, attempt + 1)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result("blocked")

            if "oops something's not right" in lower:
                logger.info("[Instamart] %s: Oops error page — item not available", city)
                if proxy_manager:
                    proxy_manager.report_success(proxy)
                return {
                    "product_id": item_id,
                    "city": city,
                    "title": None,
                    "price": None,
                    "mrp": None,
                    "status": "not_found",
                    "is_sold_out": False,
                    "url": product_url,
                    "checked_at": now,
                    "error_message": None,
                }

            # ── Find the script tag containing ___INITIAL_STATE___ + item data ──
            scripts = re.findall(r"<script.*?>(.*?)</script>", content, re.DOTALL)
            target_script = None
            has_initial_state = False
            for s in scripts:
                if "window.___INITIAL_STATE___" in s:
                    has_initial_state = True
                    if item_id in s:
                        target_script = s
                        break

            if not target_script:
                if has_initial_state:
                    logger.info(
                        "[Instamart] %s: initial state found but item_id missing — item not available",
                        city,
                    )
                    if proxy_manager:
                        proxy_manager.report_success(proxy)
                    return {
                        "product_id": item_id,
                        "city": city,
                        "title": None,
                        "price": None,
                        "mrp": None,
                        "status": "not_found",
                        "is_sold_out": False,
                        "url": product_url,
                        "checked_at": now,
                        "error_message": None,
                    }
                else:
                    logger.warning(
                        "[Instamart] %s: no ___INITIAL_STATE___ script found (page title may indicate block)",
                        city,
                    )
                    if proxy_manager:
                        proxy_manager.report_failure(proxy)
                    if attempt < max_proxy_attempts:
                        continue
                    return _error_result("state_script_not_found")

            # ── Extract and parse the embedded JSON (brace-aware) ─────────
            try:
                data = _extract_initial_state(target_script)
            except ValueError as exc:
                logger.warning(
                    "[Instamart] %s: failed to extract state JSON — %s", city, exc
                )
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result(f"json_extract_failed: {exc}")
            except json.JSONDecodeError:
                logger.warning("[Instamart] %s: invalid JSON in embedded state", city)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result("invalid_json")

            # ── Find the product node in the state tree ───────────────────
            items = _find_items(data, item_id)
            if not items:
                logger.warning(
                    "[Instamart] %s: item %s not found in parsed state", city, item_id
                )
                if proxy_manager:
                    proxy_manager.report_success(proxy)
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
                    "error_message": None,
                }

            # ── Extract price / title / stock ─────────────────────────────
            product = _extract_price_and_stock(items[0], target_variant_name)

            if product["price"] is None and not product["is_sold_out"]:
                logger.warning("[Instamart] %s: no price extracted (not sold out)", city)
                if proxy_manager:
                    proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    continue
                return _error_result("extraction_failed")

            logger.info(
                "[Instamart] %s: OK — %s = Rs.%s (MRP Rs.%s)",
                city, product["title"], product["price"], product["mrp"],
            )
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
                "error_message": None,
            }

        except (RequestsError, TimeoutError) as e:
            logger.error("[Instamart] %s: network error on attempt %d — %s", city, attempt + 1, e)
            if proxy_manager:
                proxy_manager.report_failure(proxy)
            if attempt < max_proxy_attempts:
                continue
            return _error_result(f"network_error: {e}")

        except Exception as e:
            logger.error(
                "[Instamart] %s: unexpected error on attempt %d — %s", city, attempt + 1, e
            )
            if proxy_manager:
                proxy_manager.report_failure(proxy)
            if attempt < max_proxy_attempts:
                continue
            return _error_result(f"unexpected: {e}")

        finally:
            session.close()

    return _error_result("max_retries_exceeded")
