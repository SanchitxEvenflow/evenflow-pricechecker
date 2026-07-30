"""FK Minutes cookie management — load, check expiry, and auto-refresh the `at` JWT."""

import base64
import json
import logging
from datetime import datetime, timezone, timedelta

from curl_cffi import requests as cffi

logger = logging.getLogger(__name__)

_MSITE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36 FKUA/msite/0.0.4/msite/Mobile"
)
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def parse_cookie_str(s: str) -> dict[str, str]:
    """Split 'K=V; K2=V2' into a dict, handling values that contain '='."""
    result: dict[str, str] = {}
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        eq = part.find("=")
        if eq == -1:
            result[part] = ""
        else:
            result[part[:eq]] = part[eq + 1:]
    return result


def at_expiry(cookie_str: str) -> datetime | None:
    """Decode the `at` JWT and return its expiry as a UTC datetime."""
    at_value = next(
        (v for k, v in parse_cookie_str(cookie_str).items() if k.strip() == "at"),
        None,
    )
    if not at_value:
        return None
    try:
        parts = at_value.split(".")
        if len(parts) < 2:
            return None
        padding = "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(parts[1] + padding))
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, tz=timezone.utc)
    except Exception as e:
        logger.warning("[FKM] at JWT decode failed: %s", e)
    return None


def needs_refresh(cookie_str: str) -> bool:
    """Return True if `at` is missing, already expired, or expires within 5 days."""
    exp = at_expiry(cookie_str)
    if exp is None:
        return True
    return exp - datetime.now(tz=timezone.utc) < timedelta(days=5)


async def refresh_fkm_cookies(cookie_str: str) -> str:
    """
    Refresh expired session cookies by visiting flipkart.com with just the T cookie.
    FK issues a fresh `at` (and other session cookies) in Set-Cookie headers.
    The T cookie (device ID + Bengaluru location) is preserved unchanged.
    """
    cookies = parse_cookie_str(cookie_str)
    t_value = cookies.get("T", "")
    if not t_value:
        logger.error("[FKM] No T cookie found — cannot refresh")
        return cookie_str

    seed_cookie = f"T={t_value}; vw=1280; vh=900; dpr=1"
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-IN,en;q=0.9",
        "user-agent": _CHROME_UA,
        "x-user-agent": _MSITE_UA,
    }

    try:
        resp = cffi.get(
            "https://www.flipkart.com/",
            headers={**headers, "cookie": seed_cookie},
            impersonate="chrome124",
            timeout=20,
            allow_redirects=True,
        )
    except Exception as e:
        logger.error("[FKM] Cookie refresh HTTP error: %s", e)
        return cookie_str

    # Merge response cookies into existing dict; always keep T as-is
    updated = dict(cookies)
    for name, value in resp.cookies.items():
        if name != "T":
            updated[name] = value

    new_str = "; ".join(f"{k}={v}" for k, v in updated.items())

    new_exp = at_expiry(new_str)
    if new_exp:
        logger.info("[FKM] Cookie refreshed — new at expires %s", new_exp.isoformat())
    else:
        logger.warning("[FKM] Cookie refresh done but could not verify new at expiry")

    return new_str


async def bootstrap_fkm_cookies(browser_manager, pincode: str = "560102") -> str:
    """
    Automate the initial acquisition of Flipkart Minutes cookies (T, at, SN)
    by launching a headless Playwright page and explicitly setting a Bengaluru pincode.
    """
    logger.info("[FKM] Bootstrapping fresh session cookies via Playwright...")
    context = None
    try:
        try:
            browser = await browser_manager.acquire()
        except RuntimeError:
            logger.error("[FKM] No browsers available in pool")
            return ""
            
        context = await browser.new_context()
        page = await context.new_page()
        
        # 1. Visit grocery page to initialize FKM session
        await page.goto("https://www.flipkart.com/grocery-supermart-store", wait_until="networkidle", timeout=30000)
        
        # 2. Open location modal
        try:
            # Click the location div in the header
            location_trigger = page.locator("text='Select delivery location'").first
            await location_trigger.click(timeout=5000)
        except Exception:
            pass # Modal might auto-open
            
        # 3. Enter pincode and submit
        pincode_input = page.locator("input[placeholder*='pin code' i], input[placeholder*='pincode' i]").first
        await pincode_input.fill(pincode, timeout=10000)
        
        # Wait for suggestions to load
        await page.wait_for_timeout(2000)
        
        try:
            suggestions = page.locator(f"div:has-text('{pincode}')")
            count = await suggestions.count()
            if count > 1:
                await suggestions.nth(1).click(timeout=3000)
            else:
                await pincode_input.press("Enter")
            await page.wait_for_timeout(3000)
        except Exception:
            pass
        
        # 4. Harvest cookies
        cookies = await context.cookies()
        
        # 5. Extract target cookies
        target_names = {"T", "at", "SN"}
        cookie_parts = []
        for c in cookies:
            if c["name"] in target_names:
                cookie_parts.append(f"{c['name']}={c['value']}")
                
        cookie_str = "; ".join(cookie_parts)
        
        if "at=" in cookie_str and "T=" in cookie_str:
            exp = at_expiry(cookie_str)
            logger.info("[FKM] Playwright bootstrap SUCCESS — at expires %s", exp.isoformat() if exp else "unknown")
            return cookie_str
        else:
            logger.warning("[FKM] Playwright bootstrap incomplete. Cookies: %s", cookie_str)
            return cookie_str
            
    except Exception as e:
        logger.error("[FKM] Playwright bootstrap failed: %s", e)
        return ""
    finally:
        if context:
            await context.close()
