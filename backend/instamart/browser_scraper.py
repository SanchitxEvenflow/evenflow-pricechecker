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

import asyncio
import logging
import os
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
_SESSION_BATCH_SIZE = max(1, int(os.getenv("INSTAMART_SESSION_BATCH_SIZE", "25")))


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
    try:
        await ctx.route("**/*", _block_heavy)
        page = await ctx.new_page()

        # Landing on the home page solves the WAF challenge and exposes the GPS button.
        await _goto_ok(page, _HOME_URL)
        try:
            gps = page.locator("[data-testid='set-gps-button']")
            await gps.click(timeout=6000)
            await page.wait_for_timeout(3500)  # let store resolve from coords
        except Exception as e:
            logger.warning("[Instamart] %s: set-gps click skipped/failed: %s", loc.get("name"), e)
            raise RuntimeError("delivery location setup failed") from e
        return ctx, page
    except BaseException:
        await ctx.close()
        raise


async def close_ctx(ctx):
    try:
        if ctx is not None:
            await asyncio.wait_for(ctx.close(), timeout=10)
    except Exception:
        pass


async def _goto_ok(page, url: str, tries: int = 4) -> bool:
    """Navigate, retrying on soft-block/error interstitials. True if a clean page loaded."""
    for i in range(tries):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if url != _HOME_URL:
                try:
                    await page.wait_for_function(
                        """() => {
                            const body = (document.body?.innerText || '').toLowerCase();
                            const price = document.querySelector(
                                "[data-testid='item-offer-price'], [data-testid='item-mrp-price']");
                            return (price && /[0-9]/.test(price.textContent || '')) ||
                                 ['sold out', 'out of stock', 'notify me', 'something went wrong',
                                  'request blocked', 'your request looks automated'].some(x => body.includes(x));
                        }""",
                        timeout=3500,
                    )
                except Exception:
                    pass  # preserve the old 3.5s ceiling for unserviceable/slow pages
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
        return result(title=title, error_message="product_data_incomplete")

    if sold_out and add_ct == 0:
        return result(title=title, price=offer, mrp=mrp if mrp is not None else offer, status="out_of_stock", is_sold_out=True)

    price = offer if offer is not None else mrp
    if price is None:
        return result(title=title, error_message="price_not_found")

    logger.info("[Instamart] %s: OK %s price=%s mrp=%s", city, item_id, price, mrp)
    return result(title=title, price=price, mrp=mrp if mrp is not None else price, status="available", is_sold_out=False)


async def scrape_one(browser, loc: dict, item_id: str, target_variant_name: str | None = None) -> dict:
    """Use the same bounded recovery for single and bulk lookups."""
    results = await sweep_city(browser, loc, [item_id])
    return results[item_id.strip()]


async def sweep_city(browser, loc: dict, item_ids, on_result=None, recycle_after_failures: int = 3) -> dict:
    """Sweep with bounded per-item attempts; setup failures never skip later PIDs."""
    pids = list(dict.fromkeys(pid.strip() for pid in item_ids if pid.strip()))
    snowpad = get_snowpad_provider()
    results = {}
    ctx = page = None
    session_id = None
    item_timeout = float(os.getenv("INSTAMART_ITEM_TIMEOUT_SECONDS", "240"))

    async def close_session():
        nonlocal ctx, page, session_id
        try:
            await close_ctx(ctx)
        finally:
            ctx = page = None
            if session_id is not None:
                await snowpad.close_bridge(session_id)
                session_id = None

    async def reset_context():
        nonlocal ctx, page, session_id
        await close_session()
        for attempt in range(3):
            session_id = uuid.uuid4().hex[:8]
            try:
                ctx, page = await asyncio.wait_for(
                    open_city_page(browser, loc, session_id=session_id), timeout=120,
                )
                return
            except Exception:
                await close_session()
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))

    await snowpad.acquire_slot()
    try:
        pending = pids
        for pass_index in range(2):
            retry_ids = []
            consecutive_fail = 0
            for n, pid in enumerate(pending):
                try:
                    if page is None or n % _SESSION_BATCH_SIZE == 0 or consecutive_fail >= recycle_after_failures:
                        await reset_context()
                        consecutive_fail = 0
                    result = await asyncio.wait_for(
                        scrape_item(page, pid, loc["name"]), timeout=item_timeout,
                    )
                except Exception as exc:
                    result = {
                        "product_id": pid, "city": loc["name"], "title": None,
                        "price": None, "mrp": None, "status": "error",
                        "is_sold_out": False, "url": _ITEM_URL.format(item_id=pid),
                        "checked_at": datetime.now(IST).isoformat(),
                        "error_message": str(exc) or type(exc).__name__,
                    }
                    await close_session()
                results[pid] = result
                if result.get("status") == "error":
                    consecutive_fail += 1
                    if pass_index == 0:
                        retry_ids.append(pid)
                        continue
                else:
                    consecutive_fail = 0
                if on_result is not None:
                    on_result(pid, result)
            if not retry_ids:
                break
            pending = retry_ids
    finally:
        try:
            await close_session()
        finally:
            snowpad.release_slot()
    return results
