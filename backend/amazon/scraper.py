"""Amazon.in price scraper using Playwright + BeautifulSoup4."""

import asyncio
import logging
import os
import random
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from dotenv import load_dotenv
from playwright.async_api import Browser

from proxy.manager import ProxyManager
from utils.headers import UA_POOL

load_dotenv()
logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

DELAY_MIN = float(os.getenv("AMAZON_DELAY_MIN", "3.0"))
DELAY_MAX = float(os.getenv("AMAZON_DELAY_MAX", "7.0"))

DEBUG_MODE = os.getenv("AMAZON_DEBUG", "false").lower() == "true"
DEBUG_DIR = Path("debug_amazon")

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });
window.chrome = { runtime: {} };
"""

PRICE_SELECTORS = [
    "#corePrice_feature_div span.a-offscreen",
    ".apexPriceToPay span.a-offscreen",
    "#price_inside_buybox",
    "#newBuyBoxPrice",
    "#tp_price_block_total_price_ww span.a-offscreen",
]

MRP_SELECTORS = [
    "#corePriceDisplay_desktop_feature_div .a-text-price span.a-offscreen",
    ".basisPrice span.a-offscreen",
    "#listPrice span.a-offscreen",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
]

RATING_SELECTORS = [
    "#acrPopover .a-icon-alt",
    "#averageCustomerReviews .a-icon-alt",
    "span[data-hook='rating-out-of-text']",
]

RATING_COUNT_SELECTORS = [
    "#acrCustomerReviewText",
    "#acrCustomerReviewLink span",
    "span[data-hook='total-review-count']",
]

RATING_BREAKDOWN_SELECTORS = [
    "div[data-csa-c-content-id='customerReviews-histogram']",
    "#histogramTable",
    "[data-hook='cr-ratings-histogram']",
    ".cr-ratings-histogram",
    "[data-hook='histogram-table']",
    ".a-histogram",
]

BREADCRUMB_SELECTORS = [
    "#wayfinding-breadcrumbs_feature_div ul li span.a-list-item",
    "#wayfinding-breadcrumbs_container ul li span.a-list-item",
    "ul.a-unordered-list.a-horizontal.a-size-small li span.a-list-item",
]

DETAILS_SELECTORS = [
    "#detailBullets_feature_div",
    "#prodDetails",
    "#productDetails_detailBullets_sections1",
    "#productDetails_techSpec_section_1",
]

_BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


def _extract_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            return el.get_text(" ", strip=True)
    return None


def _extract_rating(soup: BeautifulSoup) -> str | None:
    raw = _extract_text(soup, RATING_SELECTORS)
    if raw:
        match = re.search(r"([\d.]+)\s*out of", raw)
        if match:
            return match.group(1)
        match = re.search(r"([\d.]+)", raw)
        if match:
            return match.group(1)
    return None


def _extract_rating_count(soup: BeautifulSoup) -> str | None:
    raw = _extract_text(soup, RATING_COUNT_SELECTORS)
    if raw:
        match = re.search(r"([\d,]+)", raw)
        if match:
            return match.group(1)
    return None

def _extract_rating_breakdown(soup: BeautifulSoup) -> dict[str, str | None]:
    breakdown = {"5_star": None, "4_star": None, "3_star": None, "2_star": None, "1_star": None}
    container = None
    for sel in RATING_BREAKDOWN_SELECTORS:
        container = soup.select_one(sel)
        if container:
            break
    search_root = container if container else soup
    for el in search_root.find_all(attrs={"aria-label": True}):
        label = el["aria-label"]
        for i in range(5, 0, -1):
            if breakdown[f"{i}_star"]:
                continue
            m = re.search(rf"(\d+)\s*percent.*?{i}\s*star", label, re.I) or \
                re.search(rf"{i}\s*star.*?(\d+)\s*percent", label, re.I)
            if m:
                breakdown[f"{i}_star"] = f"{m.group(1)}%"
    return breakdown

def _extract_best_seller_rank(soup: BeautifulSoup) -> dict:
    empty = {
        "rank_raw": None,
        "rank_value": None,
        "rank_category": None,
        "sub_rank_value": None,
        "sub_rank_category": None,
    }

    # 1) Try specific detail blocks
    selectors = [
        "#detailBullets_feature_div",
        "#detailBulletsWrapper_feature_div",
        "#prodDetails",
        "#productDetails_detailBullets_sections1",
        "#productDetails_techSpec_section_1",
        "#productDetails_db_sections",
    ]

    text = None
    for selector in selectors:
        block = soup.select_one(selector)
        if not block:
            continue
        block_text = block.get_text(" ", strip=True)
        if "Best Sellers Rank" in block_text:
            text = block_text
            break

    # 2) Full-page fallback
    if not text:
        full_text = soup.get_text(" ", strip=True)
        m = re.search(r"Best Sellers Rank(.{0,1200})", full_text, re.I)
        if m:
            text = "Best Sellers Rank " + m.group(1)

    if not text:
        return empty

    matches = re.findall(
        r"#([\d,]+)\s+in\s+(.+?)(?=\s*\(|\s+#|$)",
        text,
    )
    matches = [(n.replace(",", ""), c.strip()) for n, c in matches if c.strip()]

    result = empty.copy()
    result["rank_raw"] = text

    if matches:
        result["rank_value"] = matches[0][0]
        result["rank_category"] = matches[0][1]
    if len(matches) > 1:
        result["sub_rank_value"] = matches[1][0]
        result["sub_rank_category"] = matches[1][1]

    return result


def _extract_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    for selector in BREADCRUMB_SELECTORS:
        elements = soup.select(selector)
        if elements:
            crumbs = [el.get_text(" ", strip=True) for el in elements]
            if crumbs:
                return crumbs
    return []

def _extract_category_hierarchy(soup: BeautifulSoup) -> dict:
    crumbs = _extract_breadcrumbs(soup)
    # Remove separators and generic root items
    crumbs = [c for c in crumbs if c and c.lower() not in {"home", "amazon.in", "›", ">"}]

    parent_node = crumbs[0] if len(crumbs) >= 1 else None
    child_node = crumbs[-1] if len(crumbs) >= 2 else None

    return {
        "parent_node": parent_node,
        "child_node": child_node,
        "category_path": " > ".join(crumbs) if crumbs else None,
    }


async def _block_resources(route) -> None:
    if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()


def _detect_status(soup: BeautifulSoup, response_text: str, asin: str, page_url: str = "") -> str:
    lower_text = response_text.lower()
    if "captcha" in lower_text or "robot check" in lower_text or "continue shopping" in lower_text:
        logger.warning("BLOCKED: bot-challenge page for %s (response_len=%d)", asin, len(response_text))
        return "blocked"

    availability_el = soup.select_one("#availability")
    if availability_el:
        avail_text = availability_el.get_text(strip=True).lower()
        if "currently unavailable" in avail_text or "out of stock" in avail_text:
            # Only mark unavailable if no price is visible — product may still be listed
            has_price = any(soup.select_one(sel) for sel in PRICE_SELECTORS)
            if not has_price:
                return "unavailable"

    canonical = soup.select_one('link[rel="canonical"]')
    if canonical and canonical.get("href"):
        canonical_href = canonical["href"]
        match = re.search(r"/dp/([A-Z0-9]{10})", canonical_href, re.IGNORECASE)
        if match and match.group(1).upper() != asin.upper():
            return "suppressed"

    title_el = soup.select_one("#productTitle")
    if not title_el:
        logger.warning("not_found for %s — landed_url=%s body_start=%r", asin, page_url, response_text[:300])
        return "not_found"

    return "check_price"


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


async def _handle_interstitial(page) -> bool:
    """Click through Amazon's 'Continue shopping' bot-check interstitial if present."""
    try:
        body = await page.inner_text("body")
        if "continue shopping" not in body.lower():
            return False

        logger.info("Interstitial detected — attempting to click through")
        for selector in ["input[type='submit']", "button", "a:has-text('Continue shopping')"]:
            try:
                await page.click(selector, timeout=4000)
                break
            except Exception:
                continue

        await page.wait_for_load_state("networkidle", timeout=15000)
        # Wait for product title + ratings section
        try:
            await page.wait_for_selector("#productTitle", timeout=10000)
            # Wait extra for ratings widget
            await page.wait_for_selector("[data-hook*='ratings'], .cr-ratings-histogram, #acrCustomerReviewLink", 
                                         timeout=8000)
        except Exception:
            pass

        logger.info("Post-interstitial page: %s", page.url)
        return True

    except Exception as e:
        logger.warning("Interstitial handler error: %s", e)
        return False


async def _save_debug(page, asin: str, attempt: int) -> None:
    """Save screenshot and HTML dump for debugging (when AMAZON_DEBUG=true)."""
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        ts = datetime.now(IST).strftime("%H%M%S")
        await page.screenshot(path=str(DEBUG_DIR / f"{asin}_{ts}_attempt{attempt + 1}.png"), full_page=True)
        html = await page.content()
        (DEBUG_DIR / f"{asin}_{ts}_attempt{attempt + 1}.html").write_text(html, encoding="utf-8")
        logger.info("Debug files saved to %s/", DEBUG_DIR)
    except Exception as e:
        logger.warning("Debug save failed: %s", e)



def _fetch_curl_data_sync(asin: str) -> dict:
    """Single direct curl_cffi request to extract rating breakdown + BSR + category.

    Proxies return a bot-check page for curl traffic, so we go direct.
    curl_cffi has no JS → Amazon serves a-no-js static HTML with histogram and product details.
    """
    _empty_breakdown = {"5_star": None, "4_star": None, "3_star": None, "2_star": None, "1_star": None}
    _empty_rank = {"rank_raw": None, "rank_value": None, "rank_category": None, "sub_rank_value": None, "sub_rank_category": None}
    _empty_category = {"parent_node": None, "child_node": None, "category_path": None}
    url = f"https://www.amazon.in/dp/{asin}"
    try:
        resp = curl_requests.get(
            url,
            impersonate="chrome120",
            proxies=None,
            timeout=20,
            headers={
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        if resp.status_code != 200:
            logger.warning("Curl data fetch: HTTP %d for ASIN %s", resp.status_code, asin)
            return {**_empty_breakdown, **_empty_rank, **_empty_category}
        soup = BeautifulSoup(resp.text, "html.parser")
        breakdown = _extract_rating_breakdown(soup)
        rank_info = _extract_best_seller_rank(soup)
        category_info = _extract_category_hierarchy(soup)
        logger.info("Curl data for %s: rank=%s/%s, breakdown_5star=%s",
                    asin, rank_info["rank_value"], rank_info["rank_category"], breakdown.get("5_star"))
        return {**breakdown, **rank_info, **category_info}
    except Exception as e:
        logger.warning("Curl data fetch error for ASIN %s: %s", asin, e)
        return {**_empty_breakdown, **_empty_rank, **_empty_category}


async def _fetch_curl_data(asin: str) -> dict:
    return await asyncio.to_thread(_fetch_curl_data_sync, asin)


async def scrape_amazon(asin: str, browser: Browser, proxy_manager: ProxyManager) -> dict:
    """
    Scrape Amazon.in product page for price data using a real Playwright browser context.

    Tries up to min(5, pool_size) proxies then falls back to a direct connection.
    Always returns a dict — never raises exceptions to the caller.
    """
    url = f"https://www.amazon.in/dp/{asin}"

    _empty = {
        "asin": asin, "price": "", "mrp": None, "rating": None, "rating_count": None,
        "rating_breakdown": None,
        "rank_raw": None, "rank_value": None, "rank_category": None,
        "sub_rank_value": None, "sub_rank_category": None,
        "parent_node": None, "child_node": None, "category_path": None,
        "platform": "amazon", "url": url,
    }

    max_proxy_attempts = min(5, len(proxy_manager.active_pool) or 1)
    context = None

    for attempt in range(max_proxy_attempts + 1):  # +1 = direct-connection fallback
        proxy = None
        try:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            logger.info("Amazon scrape attempt %d/%d for ASIN %s — waiting %.1fs",
                        attempt + 1, max_proxy_attempts + 1, asin, delay)
            await asyncio.sleep(delay)

            if attempt == max_proxy_attempts:
                proxy = None
                logger.info("All proxies exhausted — trying direct connection for ASIN %s", asin)
            else:
                proxy = proxy_manager.get_proxy()

            user_agent = random.choice(UA_POOL)
            context_opts: dict = {
                "viewport": {"width": 1920, "height": 1080},
                "user_agent": user_agent,
                "locale": "en-IN",
                "timezone_id": "Asia/Kolkata",
            }
            if proxy:
                context_opts["proxy"] = _parse_proxy(proxy)

            context = await browser.new_context(**context_opts)
            await context.add_init_script(STEALTH_SCRIPT)
            await context.route("**/*", _block_resources)
            page = await context.new_page()

            logger.info("Navigating to %s via proxy=%s", url, proxy)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            logger.info("Page landed at: %s", page.url)
            await _handle_interstitial(page)

            # Wait for product title to appear — handles deferred JS rendering
            try:
                await page.wait_for_selector("#productTitle", timeout=8000)
            except Exception:
                pass  # _detect_status will return not_found if still missing


            html = await page.content()
            body_text = await page.inner_text("body")
            soup = BeautifulSoup(html, "html.parser")

            if DEBUG_MODE:
                await _save_debug(page, asin, attempt)

            status = _detect_status(soup, body_text, asin, page_url=page.url)

            if status == "blocked":
                proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    logger.warning("Blocked on attempt %d for ASIN %s — retrying with new proxy", attempt + 1, asin)
                    await _safe_close_context(context)
                    context = None
                    await asyncio.sleep(5)
                    continue
                return {**_empty, "status": "blocked", "checked_at": datetime.now(IST).isoformat()}

            if status in ("unavailable", "suppressed", "not_found"):
                proxy_manager.report_success(proxy)
                return {**_empty, "status": status, "checked_at": datetime.now(IST).isoformat()}

            price = _extract_text(soup, PRICE_SELECTORS)
            mrp = _extract_text(soup, MRP_SELECTORS)
            rating = _extract_rating(soup)
            rating_count = _extract_rating_count(soup)
            curl_data = await _fetch_curl_data(asin)

            buy_button = soup.select_one("#add-to-cart-button") or soup.select_one("#buy-now-button")
            final_status = "available" if (price and buy_button) else "price_found"

            proxy_manager.report_success(proxy)

            logger.info("Amazon scraped ASIN %s: price=%s, rating=%s, status=%s", asin, price, rating, final_status)

            return {
                "asin": asin,
                "price": price or "",
                "mrp": mrp,
                "rating": rating,
                "rating_count": rating_count,
                "rating_breakdown": {k: curl_data[k] for k in ("5_star", "4_star", "3_star", "2_star", "1_star")},
                "rank_raw": curl_data["rank_raw"],
                "rank_value": curl_data["rank_value"],
                "rank_category": curl_data["rank_category"],
                "sub_rank_value": curl_data["sub_rank_value"],
                "sub_rank_category": curl_data["sub_rank_category"],
                "parent_node": curl_data["parent_node"],
                "child_node": curl_data["child_node"],
                "category_path": curl_data["category_path"],
                "status": final_status,
                "platform": "amazon",
                "url": url,
                "checked_at": datetime.now(IST).isoformat(),
            }

        except Exception as e:
            logger.exception("Amazon scrape error for ASIN %s (attempt %d): %s", asin, attempt + 1, str(e))
            proxy_manager.report_failure(proxy)
            await _safe_close_context(context)
            context = None
            if attempt < max_proxy_attempts:
                continue
            return {**_empty, "status": "error", "message": str(e), "checked_at": datetime.now(IST).isoformat()}

        finally:
            await _safe_close_context(context)
            context = None

    return {**_empty, "status": "error", "message": "Max retries exceeded", "checked_at": datetime.now(IST).isoformat()}
