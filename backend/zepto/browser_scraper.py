"""
zepto/browser_scraper.py
Playwright DOM scraper for Zepto.

Why this exists (2026 change): Zepto's BFF (bff-gateway.zepto.com) sits behind
AWS WAF, which returns HTTP 202 (empty body, x-amzn-waf-action: challenge) to
every curl_cffi request regardless of proxy/IP — confirmed even a bare direct
request from a residential IP gets challenged. It's a JS-execution challenge,
not an IP reputation block, so Snowpad proxy rotation (zepto/scraper.py's old
fetch_zepto_data) can never pass it. A Cloudflare Worker can't either — it's
just another server-side fetch with no JS engine.

Approach (mirrors instamart/browser_scraper.py, which hit the identical
AWS WAF problem):
  - Render the site in a real browser (the WAF JS challenge solves itself).
  - Set delivery location per-city by spoofing GPS geolocation on the context
    and clicking Zepto's "Use My Current Location" option.
  - Zepto's PDP is server-rendered: the exact same product/storeProduct JSON
    the old curl scraper parsed from the BFF response is embedded verbatim in
    the page HTML (React Server Components payload). We regex/brace-extract
    those two objects and feed them straight into the existing
    zepto.scraper._extract_zepto_product() — no need to duplicate extraction
    logic or scrape fragile hashed CSS classes.
"""

import json
import logging
import random
import uuid
from datetime import datetime, timezone, timedelta

from proxy.socks5_provider import get_provider as get_snowpad_provider
from zepto.scraper import _extract_zepto_product

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_BLOCK_TYPES = {"image", "font", "media"}

_HOME_URL = "https://www.zepto.com/"
# Slug segment must NOT be the literal word "product" — Zepto's WAF has a
# separate, much stricter rate rule keyed on exactly that generic placeholder
# (every naive scraper's URL shape). Real slug text, or even a single dummy
# character, resolves the challenge normally; "product" gets a hard 429 even
# on the WAF's own auto-retry after solving the JS challenge. Confirmed via
# side-by-side testing 2026-08-15 (same session, same IP, only slug changed).
_ITEM_URL = "https://www.zepto.com/pn/x/pvid/{item_id}"


async def _block_heavy(route):
    try:
        if route.request.resource_type in _BLOCK_TYPES:
            await route.abort()
        else:
            await route.continue_()
    except Exception:
        pass


def _extract_balanced(s: str, start: int) -> str | None:
    """Return the substring of a balanced {...} object starting at index `start`."""
    depth = 0
    i = start
    in_str = False
    esc = False
    while i < len(s):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
        i += 1
    return None


def _find_object(text: str, key: str) -> dict | None:
    marker = f'"{key}":{{'
    idx = text.find(marker)
    if idx == -1:
        return None
    raw = _extract_balanced(text, idx + len(marker) - 1)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _extract_from_html(html: str) -> dict | None:
    """
    Pull the embedded product/storeProduct JSON out of a Zepto PDP page and run
    it through the same field-mapping logic the old BFF-response parser used.
    Returns None if neither object is present (page loaded but product data
    never rendered — treated as unserviceable at this store by the caller).
    """
    text = html.replace('\\"', '"')  # RSC payload double-escapes quotes
    store_product = _find_object(text, "storeProduct")
    product = _find_object(text, "product")
    if store_product is None and product is None:
        return None
    fake_response = {
        "pageLayout": {"pageData": {"productInfo": {
            "product": product or {},
            "storeProduct": store_product or {},
        }}}
    }
    return _extract_zepto_product(fake_response)


async def open_city_page(browser, loc: dict, session_id: str | None = None):
    """
    Create a WAF-passing, location-set (context, page) for one city.
    Reuse the returned page across many scrape_item() calls, then close_ctx().
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

    await _goto_ok(page, _HOME_URL)
    try:
        await page.locator('[data-testid="user-address"]').click(timeout=15000)
        # current-location-section renders ~1s after the address modal opens
        # (async re-render) — count() right after click always reads 0. click()
        # auto-waits for it to attach instead of racing a synchronous count().
        await page.locator('[data-testid="current-location-section"]').click(timeout=15000)
        await page.wait_for_timeout(3500)  # let store resolve from coords
    except Exception as e:
        logger.warning("[Zepto] %s: location-set flow failed: %s", loc.get("name"), e)
    return ctx, page


async def close_ctx(ctx):
    try:
        await ctx.close()
    except Exception:
        pass


async def _goto_ok(page, url: str, tries: int = 4):
    """Navigate, retrying on 429 (WAF rate-limit). Returns the last Response or None."""
    resp = None
    for i in range(tries):
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)  # let RSC payload finish streaming/hydrating
        except Exception as e:
            logger.warning("[Zepto] goto error (try %d): %s", i + 1, e)
            await page.wait_for_timeout(1500)
            continue
        if resp is not None and resp.status == 429:
            logger.info("[Zepto] 429 on %s (try %d), backing off", url[:80], i + 1)
            await page.wait_for_timeout(1500 + i * 1500)
            continue
        return resp
    return resp


async def scrape_item(page, item_id: str, city: str) -> dict:
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

    resp = await _goto_ok(page, url)
    if resp is None:
        return result(error_message="navigation_failed")
    if resp.status == 404:
        return result(status="not_found", is_sold_out=True)
    if resp.status != 200:
        return result(error_message=f"http_{resp.status}")

    html = await page.content()
    extracted = _extract_from_html(html)
    if extracted is None:
        return result(
            title=f"Unserviceable at {city}",
            status="unserviceable",
            is_sold_out=True,
        )

    logger.info("[Zepto] %s: OK %s = Rs.%s", city, extracted["title"], extracted["price"])
    return result(
        title=extracted["title"],
        price=extracted["price"],
        mrp=extracted["mrp"],
        status=extracted["status"],
        is_sold_out=extracted["is_sold_out"],
    )


async def scrape_one(browser, loc: dict, item_id: str) -> dict:
    """One item in one city with a throwaway context. For interactive/single lookups."""
    snowpad = get_snowpad_provider()
    await snowpad.acquire_slot()
    try:
        session_id = uuid.uuid4().hex[:8]
        ctx, page = await open_city_page(browser, loc, session_id=session_id)
        try:
            return await scrape_item(page, item_id, loc["name"])
        finally:
            await close_ctx(ctx)
            await snowpad.close_bridge(session_id)
    finally:
        snowpad.release_slot()


async def sweep_city(browser, loc: dict, item_ids, on_result=None, recycle_after_failures: int = 3) -> dict:
    """
    Scrape every item_id for one city on a single reused context. Recycles the
    context (fresh Snowpad session) after `recycle_after_failures` consecutive
    errors. `on_result(pid, result)` is called per item if given. Returns {pid: result}.
    """
    snowpad = get_snowpad_provider()
    results: dict[str, dict] = {}
    await snowpad.acquire_slot()
    session_id = uuid.uuid4().hex[:8]
    ctx, page = await open_city_page(browser, loc, session_id=session_id)
    consecutive_fail = 0
    try:
        for n, pid in enumerate(item_ids):
            if n > 0:
                # Zepto's WAF rate-limits (429) a single IP hammering PDPs back-to-back —
                # this pacing is what the old curl scraper did too, just per-request instead
                # of once up front. Cheap insurance against burning a whole city sweep.
                await page.wait_for_timeout(random.uniform(600, 1400))
            pid = pid.strip()
            r = await scrape_item(page, pid, loc["name"])
            if r.get("status") == "error":
                consecutive_fail += 1
                if consecutive_fail >= recycle_after_failures:
                    logger.warning("[Zepto] %s: %d consecutive fails — recycling context (fresh IP)",
                                   loc["name"], consecutive_fail)
                    await close_ctx(ctx)
                    await snowpad.close_bridge(session_id)
                    snowpad.release_slot()
                    await snowpad.acquire_slot()
                    session_id = uuid.uuid4().hex[:8]
                    ctx, page = await open_city_page(browser, loc, session_id=session_id)
                    consecutive_fail = 0
                    r = await scrape_item(page, pid, loc["name"])
            else:
                consecutive_fail = 0
            results[pid] = r
            if on_result is not None:
                on_result(pid, r)
    finally:
        await close_ctx(ctx)
        await snowpad.close_bridge(session_id)
        snowpad.release_slot()
    return results
