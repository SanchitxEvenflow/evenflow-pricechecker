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
import asyncio
import logging
import os
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
_SESSION_BATCH_SIZE = max(1, int(os.getenv("ZEPTO_SESSION_BATCH_SIZE", "25")))


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
    try:
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


async def _goto_ok(page, url: str, tries: int = 4):
    """Navigate, retrying on 429 (WAF rate-limit). Returns the last Response or None."""
    resp = None
    for i in range(tries):
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
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

    # The RSC product object is often present as soon as DOMContentLoaded fires.
    # Only wait when it is not, preserving the old 3s ceiling for slow pages.
    extracted = None
    for wait_ms in (0, 400, 800, 1800):
        if wait_ms:
            await page.wait_for_timeout(wait_ms)
        extracted = _extract_from_html(await page.content())
        if extracted is not None and (extracted.get("price") is not None or extracted.get("is_sold_out")):
            break
    if extracted is None or (extracted.get("price") is None and not extracted.get("is_sold_out")):
        return result(error_message="product_data_incomplete")

    logger.info("[Zepto] %s: OK %s = Rs.%s", city, extracted["title"], extracted["price"])
    return result(
        title=extracted["title"],
        price=extracted["price"],
        mrp=extracted["mrp"],
        status=extracted["status"],
        is_sold_out=extracted["is_sold_out"],
    )


async def scrape_one(browser, loc: dict, item_id: str) -> dict:
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
    item_timeout = float(os.getenv("ZEPTO_ITEM_TIMEOUT_SECONDS", "240"))

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
                    elif n:
                        await page.wait_for_timeout(random.uniform(250, 650))
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
