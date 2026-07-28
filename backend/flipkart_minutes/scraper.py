"""FK Minutes price scraper — direct Rome API via curl_cffi, no Playwright."""

import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta

from curl_cffi import requests as cffi

from flipkart_minutes.cookie_manager import refresh_fkm_cookies, bootstrap_fkm_cookies
from flipkart_minutes.locations import LOCATIONS_BY_CITY

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

ROME_ENDPOINT = "https://1.rome.api.flipkart.com/api/4/page/fetch?cacheFirst=false"

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_MSITE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36 FKUA/msite/0.0.4/msite/Mobile"
)

_BASE_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-IN",
    "content-type": "application/json",
    "origin": "https://www.flipkart.com",
    "referer": "https://www.flipkart.com/",
    "user-agent": _CHROME_UA,
    "x-user-agent": _MSITE_UA,
    "flipkart_secure": "true",
}


def _rome_fetch(pid: str, cookie_str: str, hyperlocal: bool = True) -> dict:
    """POST to Rome API and return parsed JSON.

    Args:
        hyperlocal: If True, appends &marketplace=HYPERLOCAL (Flipkart Minutes
                    inventory). If False, uses the regular Flipkart marketplace —
                    used as a fallback when a product exists on FK but hasn't yet
                    propagated to the hyperlocal seller network.
    """
    suffix = "&marketplace=HYPERLOCAL" if hyperlocal else ""
    body = {"pageUri": f"/product/p/itme?pid={pid}{suffix}"}
    resp = cffi.post(
        ROME_ENDPOINT,
        json=body,
        headers={**_BASE_HEADERS, "cookie": cookie_str},
        impersonate="chrome124",
        timeout=20,
    )
    return resp.json()


def _has_price_widget(data: dict) -> bool:
    """Return True if the Rome response contains a PRODUCT_PRICE_SUMMARY widget."""
    slots = data.get("RESPONSE", {}).get("slots", [])
    return any(
        slot.get("widget", {}).get("type") == "PRODUCT_PRICE_SUMMARY"
        for slot in slots
    )


def _needs_cookie_refresh(data: dict) -> bool:
    """Return True when Rome signals a 406 DC Change (stale cookie)."""
    is_406 = data.get("STATUS_CODE") == 406 or data.get("ERROR_MESSAGE") == "DC Change"
    return is_406


def _extract(data: dict) -> tuple[float | None, float | None, str | None, bool]:
    """
    Walk Rome slots and extract (price, mrp, title, in_stock).
    Confirmed paths from live response:
      price  → PRODUCT_PRICE_SUMMARY.widget.data.pricing.value.finalPrice.value
      mrp    → PRODUCT_PRICE_SUMMARY.widget.data.pricing.value.prices[0].value
      title  → PRODUCT_TITLE.widget.data.titleComponent.value.title
      stock  → PRODUCT_ACTION_EXTENDED.widget.data.addToCartComponent.action.params.valid
    """
    slots = data.get("RESPONSE", {}).get("slots", [])
    price: float | None = None
    mrp: float | None = None
    title: str | None = None
    in_stock: bool = False

    for slot in slots:
        widget = slot.get("widget", {})
        wtype = widget.get("type", "")
        wd = widget.get("data", {}) or {}

        if wtype == "PRODUCT_PRICE_SUMMARY":
            pv = wd.get("pricing", {}).get("value", {})
            raw_price = pv.get("finalPrice", {}).get("value")
            if raw_price is not None:
                try:
                    price = float(raw_price)
                except (TypeError, ValueError):
                    pass
            prices_list = pv.get("prices", [])
            if prices_list:
                raw_mrp = prices_list[0].get("value")
                if raw_mrp is not None:
                    try:
                        mrp = float(raw_mrp)
                    except (TypeError, ValueError):
                        pass

        elif wtype == "PRODUCT_TITLE":
            tc = wd.get("titleComponent", {}).get("value", {})
            title = tc.get("title")

        elif wtype == "PRODUCT_ACTION_EXTENDED":
            valid = (
                wd.get("addToCartComponent", {})
                .get("action", {})
                .get("params", {})
                .get("valid")
            )
            if valid is True:
                in_stock = True

    return price, mrp, title, in_stock


async def fetch_flipkart_minutes_data(
    pid: str,
    city: str,
    app_state=None,
    **kwargs,  # absorb legacy browser=/proxy_manager= kwargs
) -> dict:
    """
    Fetch FK Minutes price for a single product via Rome API.

    Strategy:
      1. Try HYPERLOCAL marketplace (Flipkart Minutes inventory).
      2. If HYPERLOCAL returns no PRODUCT_PRICE_SUMMARY widget (product exists on
         regular FK but hasn't propagated to the hyperlocal network yet), fall back
         to a regular Flipkart call. The result is marked source="flipkart" so the
         UI/sheets layer can distinguish the two cases.

    On Rome 302 (location cookie stale), acquires fkm_cookie_lock, refreshes once,
    then retries the same call.
    """
    checked_at = datetime.now(IST).isoformat()
    url = f"https://www.flipkart.com/product/p/itme?pid={pid}&marketplace=HYPERLOCAL"

    def _err(msg: str) -> dict:
        return {
            "product_id": pid,
            "city": city,
            "title": None,
            "price": None,
            "mrp": None,
            "status": "error",
            "is_sold_out": False,
            "source": "hyperlocal",
            "url": url,
            "checked_at": checked_at,
            "error_message": msg,
        }

    if app_state is None or not getattr(app_state, "fkm_cookies", None):
        logger.error("[FKM] No fkm_cookies in app_state for pid=%s", pid)
        return _err("FK Minutes cookies not configured")

    cookie_str: str = app_state.fkm_cookies
    refreshed = False
    last_error = ""

    for attempt in range(4):
        try:
            data = await asyncio.get_running_loop().run_in_executor(
                None, _rome_fetch, pid, cookie_str, True  # HYPERLOCAL
            )
        except Exception as e:
            last_error = str(e)
            logger.warning("[FKM] Rome request error pid=%s attempt=%d: %s", pid, attempt, e)
            await asyncio.sleep(random.uniform(1.0, 3.0) + attempt * 0.5)
            continue

        if _needs_cookie_refresh(data):
            if refreshed:
                logger.error("[FKM] Still 302/406 after cookie refresh for pid=%s", pid)
                return _err("Location cookie invalid after refresh")

            logger.info("[FKM] Rome 302/406 for pid=%s — bootstrapping new cookies", pid)
            lock = getattr(app_state, "fkm_cookie_lock", None)
            
            pincode = LOCATIONS_BY_CITY.get(city, {}).get("pincode", "560102")
            if lock:
                async with lock:
                    # Re-check: another concurrent task may have already bootstrapped
                    if app_state.fkm_cookies == cookie_str:
                        app_state.fkm_cookies = await bootstrap_fkm_cookies(app_state.browser_manager, pincode=pincode)
                cookie_str = app_state.fkm_cookies
            else:
                cookie_str = await bootstrap_fkm_cookies(app_state.browser_manager, pincode=pincode)
            refreshed = True
            continue

        # ── Fallback: HYPERLOCAL returned no price widget ─────────────────────
        # This happens when a product exists on regular Flipkart but hasn't yet
        # propagated into the hyperlocal seller network (common during onboarding).
        # We retry without marketplace=HYPERLOCAL to get the regular FK price.
        if not _has_price_widget(data):
            logger.info(
                "[FKM] pid=%s — no price widget in HYPERLOCAL response, falling back to regular FK",
                pid,
            )
            try:
                data = await asyncio.get_event_loop().run_in_executor(
                    None, _rome_fetch, pid, cookie_str, False  # regular FK
                )
            except Exception as e:
                logger.warning("[FKM] FK fallback request error pid=%s: %s", pid, e)
                return _err(f"No hyperlocal price and fallback failed: {e}")
            source = "flipkart"
        else:
            source = "hyperlocal"

        price, mrp, title, in_stock = _extract(data)

        if price is None:
            status = "out_of_stock"
        else:
            # Price present → treat as available.
            # PRODUCT_ACTION_EXTENDED.valid is unreliable in Rome responses
            # (often absent even for in-stock items), so we trust price as the
            # primary availability signal.
            status = "available"

        logger.info(
            "[FKM] pid=%s city=%s price=%s mrp=%s status=%s source=%s",
            pid, city, price, mrp, status, source,
        )
        return {
            "product_id": pid,
            "city": city,
            "title": title or f"pid:{pid}",
            "price": price,
            "mrp": mrp,
            "status": status,
            "is_sold_out": status == "out_of_stock",
            "source": source,
            "url": url,
            "checked_at": checked_at,
            "error_message": None,
        }

    return _err(f"Max retries exceeded. Last error: {last_error}")
