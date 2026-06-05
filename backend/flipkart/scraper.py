"""
Flipkart.in two-step price scraper using Playwright async API.

Step A: FSN → resolve to public product URL (follows redirects)
Step B: Resolved page → scrape price, rating, rating count

Extraction strategy (in priority order):
  1. JSON-LD structured data (schema.org Product) — most reliable
  2. JavaScript evaluation on live DOM — catches dynamic content
  3. CSS selector fallbacks — legacy + newer class names
"""

import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import Browser

from proxy.manager import ProxyManager
from utils.headers import UA_POOL

load_dotenv()
logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

DELAY_MIN = float(os.getenv("FLIPKART_DELAY_MIN", "4.0"))
DELAY_MAX = float(os.getenv("FLIPKART_DELAY_MAX", "9.0"))

# Enable debug screenshots/HTML dumps (set FLIPKART_DEBUG=true in .env)
DEBUG_MODE = os.getenv("FLIPKART_DEBUG", "false").lower() == "true"
DEBUG_DIR = Path("debug_flipkart")

# Anti-detection init script
STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });
window.chrome = { runtime: {} };
"""

# ── In-memory URL cache ─────────────────────────────────────────────────────
_resolved_url_cache: dict[str, str] = {}


def _build_fsn_url(fsn: str) -> str:
    """Build the FSN bridge URL that Flipkart resolves to the public product page."""
    return f"https://www.flipkart.com/product/p/itme?pid={fsn}"


def _get_cached_url(fsn: str) -> str | None:
    return _resolved_url_cache.get(fsn)


def _cache_url(fsn: str, resolved_url: str) -> None:
    _resolved_url_cache[fsn] = resolved_url
    logger.debug("Cached resolved URL for FSN %s: %s", fsn, resolved_url)


# ── JavaScript extraction snippets ──────────────────────────────────────────

# This JS runs in the browser and returns all extractable product data at once
JS_EXTRACT_ALL = """
() => {
    const result = { price: null, mrp: null, discount: null, rating: null, rating_count: null, fulfilled_by: null };

    // ── Strategy 1: JSON-LD structured data ──
    const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const s of ldScripts) {
        try {
            const data = JSON.parse(s.textContent);
            // Can be a single object or array
            const items = Array.isArray(data) ? data : [data];
            for (const item of items) {
                if (item['@type'] === 'Product' || item['@type'] === 'IndividualProduct') {
                    // Price from offers
                    if (item.offers) {
                        const offer = Array.isArray(item.offers) ? item.offers[0] : item.offers;
                        if (offer.price) result.price = '₹' + Number(offer.price).toLocaleString('en-IN');
                        if (offer.lowPrice) result.price = '₹' + Number(offer.lowPrice).toLocaleString('en-IN');
                    }
                    // Rating
                    if (item.aggregateRating) {
                        if (item.aggregateRating.ratingValue) result.rating = String(item.aggregateRating.ratingValue);
                        if (item.aggregateRating.ratingCount) result.rating_count = String(item.aggregateRating.ratingCount);
                        if (item.aggregateRating.reviewCount && !result.rating_count) {
                            result.rating_count = String(item.aggregateRating.reviewCount);
                        }
                    }
                }
            }
        } catch(e) {}
    }

    // ── Strategy 2: Targeted CSS selectors (new Flipkart React layout) ──

    // Price + MRP: div.css-g5y9jx price container
    if (!result.price || !result.mrp) {
        const container = document.querySelector('div.css-g5y9jx');
        if (container) {
            if (!result.price) {
                for (const child of container.querySelectorAll('div')) {
                    const s = child.getAttribute('style') || '';
                    if (!s.includes('line-through')) {
                        const text = child.textContent.trim();
                        if (/^₹[\\d,]+$/.test(text)) { result.price = text; break; }
                    }
                }
            }
            if (!result.mrp) {
                for (const child of container.querySelectorAll('div')) {
                    const s = child.getAttribute('style') || '';
                    if (s.includes('line-through')) {
                        const digits = child.textContent.trim().replace(/[^\\d,]/g, '');
                        if (digits) { result.mrp = '₹' + digits; break; }
                    }
                }
            }
        }
    }

    // Rating: div.css-146c3p1 with inter_bold font (rating badge)
    if (!result.rating) {
        for (const el of document.querySelectorAll('div.css-146c3p1')) {
            const s = el.getAttribute('style') || '';
            if (s.includes('inter_bold')) {
                const val = parseFloat(el.textContent.trim());
                if (val >= 1 && val <= 5) { result.rating = String(val); break; }
            }
        }
    }

    // Rating count: "based on N ratings by" text pattern
    if (!result.rating_count) {
        for (const el of document.querySelectorAll('div, span')) {
            const m = el.textContent.trim().match(/based on ([\\d,]+)\\s*ratings?/i);
            if (m) { result.rating_count = m[1]; break; }
        }
    }

    // ── Strategy 3: Visible DOM text extraction ──
    // Price: look for ₹ symbol in likely price containers
    if (!result.price) {
        // Try all elements that contain ₹ and look like a price
        const allEls = document.querySelectorAll('div, span');
        for (const el of allEls) {
            const text = el.textContent.trim();
            // Match price patterns: ₹339 or ₹1,999
            if (/^₹[\\d,]+$/.test(text) && !el.closest('s') && !el.closest('[style*="line-through"]')) {
                // Check it's a direct text node (not deeply nested)
                const directText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join('');
                if (/^₹[\\d,]+$/.test(directText) || el.children.length === 0) {
                    result.price = text;
                    break;
                }
            }
        }
    }

    // MRP: look for strikethrough prices (Strategy 3 fallback)
    if (!result.mrp) {
        const strikeThroughs = document.querySelectorAll('s, [style*="line-through"], del');
        for (const el of strikeThroughs) {
            const text = el.textContent.trim();
            if (/₹[\\d,]+/.test(text)) {
                result.mrp = text.match(/₹[\\d,]+/)[0];
                break;
            }
        }
    }

    // Discount: look for percentage patterns
    if (!result.discount) {
        const allEls = document.querySelectorAll('div, span');
        for (const el of allEls) {
            const text = el.textContent.trim();
            if (/^[↓▼]?\\d+%\\s*off$/i.test(text) || /^[↓▼]\\d+%$/.test(text)) {
                result.discount = text;
                break;
            }
        }
    }

    // Rating: look for rating badge patterns (number followed by star)
    if (!result.rating) {
        const allEls = document.querySelectorAll('div, span');
        for (const el of allEls) {
            const text = el.textContent.trim();
            // Match "4.3" or "4.3★" but not longer strings
            if (/^[\\d.]+\\s*[★☆]?$/.test(text) && parseFloat(text) >= 1 && parseFloat(text) <= 5) {
                result.rating = text.replace(/[★☆\\s]/g, '');
                break;
            }
        }
    }

    // Rating count: look for "X Ratings" or "X Ratings & Y Reviews"
    if (!result.rating_count) {
        const allEls = document.querySelectorAll('div, span');
        for (const el of allEls) {
            const text = el.textContent.trim();
            const match = text.match(/([\\d,]+)\\s*Ratings?/i);
            if (match) {
                result.rating_count = match[1];
                break;
            }
        }
    }

    // Fulfilled by: "Fulfilled by <seller>" text in product details
    if (!result.fulfilled_by) {
        for (const el of document.querySelectorAll('div, span')) {
            const text = el.textContent.trim();
            const m = text.match(/^Fulfilled by\s+(.+)$/i);
            if (m && el.children.length === 0) {
                result.fulfilled_by = m[1].trim();
                break;
            }
        }
    }

    return result;
}
"""


# ── Main scraper ────────────────────────────────────────────────────────────

async def scrape_flipkart(fsn: str, browser: Browser, proxy_manager: ProxyManager) -> dict:
    """
    Two-step Flipkart scraper:
      Step A: Resolve FSN → canonical product URL (with redirect capture)
      Step B: Scrape buyer-facing page for price, rating, rating count

    Extraction uses JSON-LD first, then JS DOM evaluation, then CSS selectors.
    Always returns a dict — never raises exceptions to the caller.
    """
    cached_url = _get_cached_url(fsn)
    fsn_url = _build_fsn_url(fsn)
    start_url = cached_url if cached_url else fsn_url

    max_proxy_attempts = min(3, len(proxy_manager.active_pool) or 1)

    for attempt in range(max_proxy_attempts + 1):  # +1 = direct-connection fallback
        context = None
        try:
            # ── Delay ───────────────────────────────────────────────────
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            logger.info(
                "Flipkart scrape attempt %d/%d for FSN %s — waiting %.1fs (using %s)",
                attempt + 1, max_proxy_attempts + 1, fsn, delay,
                "cached URL" if cached_url and start_url == cached_url else "FSN bridge URL",
            )
            await asyncio.sleep(delay)

            # ── Browser context setup ───────────────────────────────────
            proxy = None
            if attempt == max_proxy_attempts:
                logger.info("All proxies exhausted — trying direct connection for FSN %s", fsn)
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
            page = await context.new_page()

            # ── STEP A: Navigate & resolve URL ──────────────────────────
            logger.info("Step A: Navigating to %s", start_url)
            response = await page.goto(start_url, wait_until="domcontentloaded", timeout=30000)

            # Capture final URL after redirects
            resolved_url = page.url
            logger.info("Step A: Resolved URL → %s", resolved_url)

            # If cached URL returned error, fall back to FSN bridge
            if cached_url and start_url == cached_url:
                if response and response.status >= 400:
                    logger.warning("Cached URL returned %d — falling back to FSN bridge", response.status)
                    _resolved_url_cache.pop(fsn, None)
                    await page.goto(fsn_url, wait_until="domcontentloaded", timeout=30000)
                    resolved_url = page.url

            # ── Wait for page to fully render ───────────────────────────
            # Wait for networkidle to ensure JS has rendered content
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            # Additional wait for dynamic content to settle
            await asyncio.sleep(2)

            # ── STEP B: Status detection ────────────────────────────────
            body_text = await page.inner_text("body")
            body_lower = body_text.lower()

            # Check: overloaded
            if "site is overloaded" in body_lower:
                proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    logger.warning("Flipkart overloaded for FSN %s — retrying in 10s", fsn)
                    await _safe_close_context(context)
                    context = None
                    await asyncio.sleep(10)
                    continue
                return _error_result(fsn, resolved_url, "overloaded")

            # Check: blocked / captcha
            if "access denied" in body_lower or "captcha" in body_lower:
                proxy_manager.report_failure(proxy)
                if attempt < max_proxy_attempts:
                    logger.warning("Flipkart blocked for FSN %s — retrying in 10s", fsn)
                    await _safe_close_context(context)
                    context = None
                    await asyncio.sleep(10)
                    continue
                return _error_result(fsn, resolved_url, "blocked")

            # Check: not found / 404
            if "page not found" in body_lower or "this item is no longer available" in body_lower:
                proxy_manager.report_success(proxy)
                return _error_result(fsn, resolved_url, "not_found")

            # ── Debug: save screenshot & HTML ───────────────────────────
            if DEBUG_MODE:
                await _save_debug(page, fsn, attempt)

            # ── STEP B: Extract all data via JavaScript ─────────────────
            logger.info("Step B: Extracting data from resolved page...")
            data = await page.evaluate(JS_EXTRACT_ALL)
            logger.info("JS extraction result: %s", data)

            price = data.get("price") if data else None
            mrp = data.get("mrp") if data else None
            discount = data.get("discount") if data else None
            rating = data.get("rating") if data else None
            rating_count = data.get("rating_count") if data else None
            fulfilled_by = data.get("fulfilled_by") if data else None

            # ── Fallback: regex on visible body text ────────────────────
            if not price:
                price = _extract_price_from_text(body_text)
                logger.info("Text fallback price: %s", price)

            if not rating:
                rating = _extract_rating_from_text(body_text)
                logger.info("Text fallback rating: %s", rating)

            if not rating_count:
                rating_count = _extract_rating_count_from_text(body_text)
                logger.info("Text fallback rating_count: %s", rating_count)

            # ── Determine status ────────────────────────────────────────
            if not price:
                proxy_manager.report_success(proxy)
                _cache_url(fsn, resolved_url)
                return _error_result(fsn, resolved_url, "unavailable")

            # ── Cache & return ──────────────────────────────────────────
            proxy_manager.report_success(proxy)
            _cache_url(fsn, resolved_url)

            logger.info(
                "Flipkart scraped FSN %s: price=%s, mrp=%s, discount=%s, rating=%s, count=%s, fulfilled_by=%s",
                fsn, price, mrp, discount, rating, rating_count, fulfilled_by,
            )

            return {
                "fsn": fsn,
                "price": price,
                "mrp": mrp,
                "discount": discount,
                "rating": rating,
                "rating_count": rating_count,
                "fulfilled_by": fulfilled_by,
                "status": "available",
                "platform": "flipkart",
                "url": resolved_url,
                "resolved_url": resolved_url,
                "checked_at": datetime.now(IST).isoformat(),
            }

        except Exception as e:
            logger.exception("Flipkart scrape error for FSN %s (attempt %d): %s", fsn, attempt + 1, str(e))
            if attempt < max_proxy_attempts:
                await _safe_close_context(context)
                context = None
                if cached_url:
                    _resolved_url_cache.pop(fsn, None)
                    start_url = fsn_url
                continue
            return {
                "fsn": fsn,
                "price": "",
                "mrp": None,
                "discount": None,
                "rating": None,
                "rating_count": None,
                "status": "error",
                "message": str(e),
                "platform": "flipkart",
                "url": fsn_url,
                "resolved_url": None,
                "checked_at": datetime.now(IST).isoformat(),
            }

        finally:
            await _safe_close_context(context)

    return {
        "fsn": fsn,
        "price": "",
        "mrp": None,
        "discount": None,
        "rating": None,
        "rating_count": None,
        "status": "error",
        "message": "Max retries exceeded",
        "platform": "flipkart",
        "url": fsn_url,
        "resolved_url": None,
        "checked_at": datetime.now(IST).isoformat(),
    }


# ── Text-based fallback extractors ──────────────────────────────────────────

def _extract_price_from_text(body_text: str) -> str | None:
    """Extract price from visible page text using regex."""
    # Look for ₹ followed by digits (with optional commas)
    # Match patterns like ₹339, ₹1,999, ₹12,999
    matches = re.findall(r"₹[\d,]+", body_text)
    if matches:
        # Return the first price found (usually the selling price)
        return matches[0]
    return None


def _extract_rating_from_text(body_text: str) -> str | None:
    """Extract rating from visible page text."""
    # Look for patterns like "4.3 ★" or "3.6★" or standalone decimals near rating context
    match = re.search(r"(\d\.\d)\s*[★☆]", body_text)
    if match:
        return match.group(1)
    # Fallback: look for rating pattern in text
    match = re.search(r"(\d\.\d)\s*\|", body_text)
    if match:
        val = float(match.group(1))
        if 1.0 <= val <= 5.0:
            return match.group(1)
    return None


def _extract_rating_count_from_text(body_text: str) -> str | None:
    """Extract rating count from visible page text."""
    match = re.search(r"([\d,]+)\s*Ratings?", body_text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _error_result(fsn: str, url: str, status: str) -> dict:
    """Build a standardized error/empty result dict."""
    return {
        "fsn": fsn,
        "price": "",
        "mrp": None,
        "discount": None,
        "rating": None,
        "rating_count": None,
        "status": status,
        "platform": "flipkart",
        "url": url,
        "resolved_url": url,
        "checked_at": datetime.now(IST).isoformat(),
    }


async def _save_debug(page, fsn: str, attempt: int) -> None:
    """Save screenshot and HTML for debugging (when FLIPKART_DEBUG=true)."""
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        ts = datetime.now(IST).strftime("%H%M%S")
        # Screenshot
        await page.screenshot(path=str(DEBUG_DIR / f"{fsn}_{ts}_attempt{attempt + 1}.png"), full_page=True)
        # HTML dump
        html = await page.content()
        (DEBUG_DIR / f"{fsn}_{ts}_attempt{attempt + 1}.html").write_text(html, encoding="utf-8")
        logger.info("Debug files saved to %s/", DEBUG_DIR)
    except Exception as e:
        logger.warning("Failed to save debug files: %s", e)


async def _safe_close_context(context) -> None:
    """Safely close browser context — never leak contexts."""
    if context:
        try:
            await context.close()
        except Exception:
            pass


def _parse_proxy(proxy_url: str) -> dict:
    """Parse proxy URL into Playwright's proxy format dict."""
    from urllib.parse import urlparse

    parsed = urlparse(proxy_url)
    result: dict = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        result["username"] = parsed.username
    if parsed.password:
        result["password"] = parsed.password
    return result
