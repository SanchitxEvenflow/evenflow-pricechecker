"""
instamart/browser_scraper.py
Playwright DOM scraper for Swiggy Instamart.

Why this exists (2026 change): Swiggy moved Instamart behind AWS WAF *and* dropped
SSR product data. Price no longer lives in window.___INITIAL_STATE___ — even a real
browser leaves productV2.itemData empty. Price now exists ONLY in the client-rendered
DOM. So curl_cffi/SSR parsing (the old scraper.py) is dead: with a valid aws-waf-token
you get HTTP 200 but an empty shell.

Approach:
  - Render the item page in a real browser (the WAF JS challenge solves itself).
  - Set delivery location per-city by spoofing GPS geolocation on the context and
    clicking Swiggy's "Use current location" button ([data-testid=set-gps-button]).
  - Read price/mrp/stock from DOM data-testid selectors.

Efficient shape (see callers): one context per city, location set once, reused across
all item navigations, then closed. Images/fonts/media are aborted to save RAM + time.

Reliability note: Swiggy intermittently soft-blocks even a real browser
("Something went wrong" / "Request Blocked"). _goto_ok retries those. Datacenter/VPS
IPs get blocked harder than residential — if block rate is high on the VPS, a
residential proxy on the browser context is the next lever.
"""

import logging
import re
import uuid
from datetime import datetime, timezone, timedelta

from proxy.socks5_provider import get_provider as get_snowpad_provider

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Heavy resources we never need — price is text. Aborting these is the main RAM lever.
_BLOCK_TYPES = {"image", "font", "media"}

# Substrings that mark a soft-block / error interstitial (case-insensitive).
_SOFT_ERRORS = ("something went wrong", "request blocked", "your request looks automated")

_HOME_URL = "https://www.swiggy.com/instamart"
_ITEM_URL = "https://www.swiggy.com/instamart/item/{item_id}"


async def _block_heavy(route):
    try:
        if route.request.resource_type in _BLOCK_TYPES:
            await route.abort()
        else:
            await route.continue_()
    except Exception:
        # Route may already be handled/closed during teardown — ignore.
        pass


def _to_float(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"\d[\d,]*", s)
    return float(m.group(0).replace(",", "")) if m else None


async def open_city_page(browser, loc: dict, session_id: str | None = None):
    """
    Create a WAF-passing, location-set (context, page) for one city.
    Reuse the returned page across many scrape_item() calls, then close_ctx().
    `session_id` pins a sticky Snowpad exit IP (~10 min TTL) for this context —
    the AWS WAF binds its JS-challenge token to the solving IP, so every attempt
    (initial open + each recycle) needs its own session_id for a fresh IP.
    Returns (context, page). Raises on hard failure.
    """
    snowpad = get_snowpad_provider()
    proxy = await snowpad.bridge_proxy(session_id=session_id) if snowpad.enabled else None
    ctx_opts = dict(
        user_agent=_UA,
        locale="en-IN",
        viewport={"width": 1280, "height": 900},
        geolocation={"latitude": loc["lat"], "longitude": loc["lng"]},
        permissions=["geolocation"],
    )
    if proxy:
        ctx_opts["proxy"] = proxy
    ctx = await browser.new_context(**ctx_opts)
    await ctx.route("**/*", _block_heavy)
    page = await ctx.new_page()

    # Landing on the home page solves the WAF challenge and exposes the GPS button.
    await _goto_ok(page, _HOME_URL)
    try:
        gps = page.locator("[data-testid='set-gps-button']")
        if await gps.count() > 0:
            await gps.click(timeout=6000)
            await page.wait_for_timeout(3500)  # let store resolve from coords
    except Exception as e:
        # If the button is absent, location often auto-resolves from the geolocation
        # already set on the context — not fatal, just log.
        logger.warning("[Instamart] %s: set-gps click skipped/failed: %s", loc.get("name"), e)
    return ctx, page


async def close_ctx(ctx):
    try:
        await ctx.close()
    except Exception:
        pass


async def _goto_ok(page, url: str, tries: int = 4) -> bool:
    """Navigate, retrying on soft-block/error interstitials. True if a clean page loaded."""
    for i in range(tries):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3500)  # let React render + XHRs populate DOM
        except Exception as e:
            logger.warning("[Instamart] goto error (try %d): %s", i + 1, e)
            await page.wait_for_timeout(1500)
            continue
        try:
            body = (await page.inner_text("body")).lower()
        except Exception:
            body = ""
        if not any(s in body for s in _SOFT_ERRORS):
            return True
        logger.info("[Instamart] soft-block on %s (try %d), retrying", url[:60], i + 1)
        await page.wait_for_timeout(1500 + i * 1000)
    return False


async def _testid_text(page, testid: str) -> str | None:
    el = page.locator(f"[data-testid='{testid}']").first
    try:
        if await el.count() == 0:
            return None
        return (await el.text_content() or "").strip()
    except Exception:
        return None


async def scrape_item(page, item_id: str, city: str, target_variant_name: str | None = None) -> dict:
    """
    Scrape one item on an already-located page. `page` must come from open_city_page()
    (or otherwise have the delivery location set). Returns the same dict shape the old
    curl scraper returned, so downstream formatting is unchanged.

    ponytail: takes the default/selected variant shown on the PDP. Per-city variant
    matching (target_variant_name) is accepted but not yet used — add if variants
    diverge across cities and it matters.
    """
    url = _ITEM_URL.format(item_id=item_id)
    now = datetime.now(IST).isoformat()

    def result(**kw) -> dict:
        base = {
            "product_id": item_id,
            "city": city,
            "title": None,
            "price": None,
            "mrp": None,
            "status": "error",
            "is_sold_out": False,
            "url": url,
            "checked_at": now,
            "error_message": None,
        }
        base.update(kw)
        return base

    if not await _goto_ok(page, url):
        return result(status="error", error_message="blocked_or_error_page")

    # Product name: prefer <h1>, fall back to cleaned page title.
    title = None
    try:
        h1 = page.locator("h1").first
        if await h1.count() > 0:
            title = (await h1.text_content() or "").strip() or None
    except Exception:
        pass
    if not title:
        t = await page.title()
        title = re.sub(r"^Buy\s+|\s+Online.*$", "", t).strip() or "Unknown Product"

    offer = _to_float(await _testid_text(page, "item-offer-price"))
    mrp = _to_float(await _testid_text(page, "item-mrp-price"))

    # Stock: an ADD control means purchasable. Its absence + a sold-out/notify marker
    # means out of stock. No price + no add + not sold-out => unserviceable at this city.
    add_ct = 0
    try:
        add_ct = await page.locator(
            "[data-testid='add_buttons_center'], [data-testid='buttonpair-add']"
        ).count()
    except Exception:
        pass

    body_lower = ""
    try:
        body_lower = (await page.inner_text("body")).lower()
    except Exception:
        pass
    sold_out = any(s in body_lower for s in ("sold out", "out of stock", "notify me"))

    if offer is None and mrp is None and add_ct == 0 and not sold_out:
        return result(
            title=f"Unserviceable at {city}",
            status="unserviceable",
            is_sold_out=True,
        )

    if sold_out and add_ct == 0:
        return result(title=title, price=offer, mrp=mrp if mrp is not None else offer, status="out_of_stock", is_sold_out=True)

    price = offer if offer is not None else mrp
    if price is None:
        # No price or mrp found — treat as out-of-stock rather than error
        return result(title=title, status="out_of_stock", is_sold_out=True, error_message="price_not_found")

    logger.info("[Instamart] %s: OK %s price=%s mrp=%s", city, item_id, price, mrp)
    return result(title=title, price=price, mrp=mrp if mrp is not None else price, status="available", is_sold_out=False)


async def scrape_one(browser, loc: dict, item_id: str, target_variant_name: str | None = None) -> dict:
    """One item in one city with a throwaway context. For interactive/single lookups."""
    snowpad = get_snowpad_provider()
    await snowpad.acquire_slot()
    try:
        ctx, page = await open_city_page(browser, loc, session_id=uuid.uuid4().hex[:8])
        try:
            return await scrape_item(page, item_id, loc["name"], target_variant_name)
        finally:
            await close_ctx(ctx)
    finally:
        snowpad.release_slot()


async def sweep_city(browser, loc: dict, item_ids, on_result=None, recycle_after_failures: int = 3) -> dict:
    """
    Scrape every item_id for one city on a single reused context.

    Recycles the context (close + reopen, re-set location, fresh Snowpad session) after
    `recycle_after_failures` consecutive errors — Swiggy's soft-block tends to stick to a
    flagged context, so a fresh one recovers throughput. `on_result(pid, result)` is called
    per item if given (for live progress). Returns {pid: result}.
    """
    snowpad = get_snowpad_provider()
    results: dict[str, dict] = {}
    await snowpad.acquire_slot()
    ctx, page = await open_city_page(browser, loc, session_id=uuid.uuid4().hex[:8])
    consecutive_fail = 0
    try:
        for pid in item_ids:
            pid = pid.strip()
            r = await scrape_item(page, pid, loc["name"])
            if r.get("status") == "error":
                consecutive_fail += 1
                if consecutive_fail >= recycle_after_failures:
                    logger.warning("[Instamart] %s: %d consecutive fails — recycling context (fresh IP)",
                                   loc["name"], consecutive_fail)
                    await close_ctx(ctx)
                    snowpad.release_slot()
                    await snowpad.acquire_slot()
                    ctx, page = await open_city_page(browser, loc, session_id=uuid.uuid4().hex[:8])  # fresh sticky IP
                    consecutive_fail = 0
                    r = await scrape_item(page, pid, loc["name"])  # one retry on fresh ctx
            else:
                consecutive_fail = 0
            results[pid] = r
            if on_result is not None:
                on_result(pid, r)
    finally:
        await close_ctx(ctx)
        snowpad.release_slot()
    return results
