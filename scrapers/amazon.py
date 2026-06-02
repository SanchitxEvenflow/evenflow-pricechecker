"""Amazon.in price scraper using requests + BeautifulSoup4."""

import logging
import os
import random
import re
import time
from datetime import datetime, timezone, timedelta

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from proxy.manager import ProxyManager
from utils.headers import get_headers

load_dotenv()
logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

DELAY_MIN = float(os.getenv("AMAZON_DELAY_MIN", "3.0"))
DELAY_MAX = float(os.getenv("AMAZON_DELAY_MAX", "7.0"))

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


def _extract_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    for selector in BREADCRUMB_SELECTORS:
        els = soup.select(selector)
        crumbs = [el.get_text(" ", strip=True) for el in els if el.get_text(" ", strip=True)]
        crumbs = [c for c in crumbs if c and c != ">"]
        if crumbs:
            return crumbs
    return []


def _extract_category_hierarchy(soup: BeautifulSoup) -> dict:
    crumbs = _extract_breadcrumbs(soup)
    parent_node = crumbs[0] if len(crumbs) >= 1 else None
    child_node = crumbs[1] if len(crumbs) >= 2 else None
    return {
        "parent_node": parent_node,
        "child_node": child_node,
        "category_path": " > ".join(crumbs) if crumbs else None,
    }


def _extract_best_seller_rank(soup: BeautifulSoup) -> dict:
    full_text = soup.get_text("\n", strip=True)

    rank_raw = None
    rank_value = None
    rank_category = None

    m = re.search(
        r"(Amazon Best Sellers Rank|Best Sellers Rank)\s*:?\s*(.*?)(?:\n|$)",
        full_text,
        re.IGNORECASE,
    )
    if m:
        rank_raw = m.group(2).strip()

    if not rank_raw:
        for selector in DETAILS_SELECTORS:
            el = soup.select_one(selector)
            if not el:
                continue
            details_text = el.get_text("\n", strip=True)
            m2 = re.search(
                r"(Amazon Best Sellers Rank|Best Sellers Rank)\s*:?\s*(.*?)(?:\n|$)",
                details_text,
                re.IGNORECASE,
            )
            if m2:
                rank_raw = m2.group(2).strip()
                break

    if rank_raw:
        m3 = re.search(r"#([\d,]+)\s+in\s+(.+?)(?:\(|$)", rank_raw)
        if m3:
            rank_value = m3.group(1).replace(",", "")
            rank_category = m3.group(2).strip()

    return {
        "rank_raw": rank_raw,
        "rank_value": rank_value,
        "rank_category": rank_category,
    }


def _detect_status(soup: BeautifulSoup, response_text: str, asin: str) -> str:
    lower_text = response_text.lower()
    if "captcha" in lower_text or "robot check" in lower_text:
        logger.warning("BLOCKED: CAPTCHA/robot-check for %s (response_len=%d)", asin, len(response_text))
        return "blocked"

    availability_el = soup.select_one("#availability")
    if availability_el:
        avail_text = availability_el.get_text(strip=True).lower()
        if "currently unavailable" in avail_text or "out of stock" in avail_text:
            return "unavailable"

    canonical = soup.select_one('link[rel="canonical"]')
    if canonical and canonical.get("href"):
        canonical_href = canonical["href"]
        match = re.search(r"/dp/([A-Z0-9]{10})", canonical_href, re.IGNORECASE)
        if match and match.group(1).upper() != asin.upper():
            return "suppressed"

    title_el = soup.select_one("#productTitle")
    if not title_el:
        return "not_found"

    return "check_price"


def scrape_amazon(asin: str, proxy_manager: ProxyManager) -> dict:
    """
    Scrape Amazon.in product page for price data.

    Always returns a dict — never raises exceptions to the caller.
    Tries up to min(5, pool_size) proxies before falling back to a direct connection.
    """
    url = f"https://www.amazon.in/dp/{asin}"

    _empty = {
        "asin": asin, "price": "", "mrp": None, "rating": None, "rating_count": None,
        "rank_raw": None, "rank_value": None, "rank_category": None,
        "parent_node": None, "child_node": None, "category_path": None,
        "platform": "amazon", "url": url,
    }

    max_proxy_attempts = min(5, len(proxy_manager.active_pool) or 1)

    for attempt in range(max_proxy_attempts + 1):  # +1 = direct-connection fallback
        try:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            logger.info("Amazon scrape attempt %d/%d for ASIN %s — waiting %.1fs",
                        attempt + 1, max_proxy_attempts + 1, asin, delay)
            time.sleep(delay)

            if attempt == max_proxy_attempts:
                proxy = None
                proxies = None
                logger.info("All proxies exhausted — trying direct connection for ASIN %s", asin)
            else:
                proxy = proxy_manager.get_proxy()
                proxies = {"http": proxy, "https": proxy} if proxy else None

            session = curl_requests.Session(impersonate="chrome124")
            session.headers.update(get_headers())
            if proxies:
                session.proxies.update(proxies)

            response = session.get(url, timeout=15)
            response.raise_for_status()
            logger.info("HTTP %d for %s via proxy=%s (len=%d)", response.status_code, url, proxy, len(response.text))

            soup = BeautifulSoup(response.text, "html.parser")

            status = _detect_status(soup, response.text, asin)

            if status == "blocked":
                proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    logger.warning("Blocked on attempt %d for ASIN %s — retrying with new proxy", attempt + 1, asin)
                    time.sleep(5)
                    continue
                return {**_empty, "status": "blocked", "checked_at": datetime.now(IST).isoformat()}

            if status in ("unavailable", "suppressed", "not_found"):
                proxy_manager.report_success(proxy)
                return {**_empty, "status": status, "checked_at": datetime.now(IST).isoformat()}

            price = _extract_text(soup, PRICE_SELECTORS)
            mrp = _extract_text(soup, MRP_SELECTORS)
            rating = _extract_rating(soup)
            rating_count = _extract_rating_count(soup)

            rank_info = _extract_best_seller_rank(soup)
            category_info = _extract_category_hierarchy(soup)

            buy_button = soup.select_one("#add-to-cart-button") or soup.select_one("#buy-now-button")
            final_status = "available" if (price and buy_button) else "price_found"

            proxy_manager.report_success(proxy)

            return {
                "asin": asin,
                "price": price or "",
                "mrp": mrp,
                "rating": rating,
                "rating_count": rating_count,
                "rank_raw": rank_info["rank_raw"],
                "rank_value": rank_info["rank_value"],
                "rank_category": rank_info["rank_category"],
                "parent_node": category_info["parent_node"],
                "child_node": category_info["child_node"],
                "category_path": category_info["category_path"],
                "status": final_status,
                "platform": "amazon",
                "url": url,
                "checked_at": datetime.now(IST).isoformat(),
            }

        except Exception as e:
            logger.exception("Amazon scrape error for ASIN %s (attempt %d): %s", asin, attempt + 1, str(e))
            if attempt < max_proxy_attempts:
                continue
            return {**_empty, "status": "error", "message": str(e), "checked_at": datetime.now(IST).isoformat()}

    return {
        "asin": asin,
        "price": "",
        "mrp": None,
        "rating": None,
        "rating_count": None,
        "rank_raw": None,
        "rank_value": None,
        "rank_category": None,
        "parent_node": None,
        "child_node": None,
        "category_path": None,
        "status": "error",
        "message": "Max retries exceeded",
        "platform": "amazon",
        "url": url,
        "checked_at": datetime.now(IST).isoformat(),
    }