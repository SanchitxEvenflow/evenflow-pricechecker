"""
instamart/proxy_provider.py
Sticky proxy IPs for Instamart's browser scraper — ONLY Instamart uses this.

Why: Swiggy sits behind AWS WAF, which binds its challenge token to the IP that
solved it. The webshare *rotating* endpoint (used by the other scrapers via
proxies.txt) hands out a fresh IP per connection, which invalidates the token every
request → constant re-challenge/block. So for Instamart we instead pull concrete,
non-rotating proxy IPs from the Webshare API (WBBSHARE_API) and pin one IP per browser
context. Each context keeps its own sticky IP for the whole city sweep.

The other scrapers (Amazon/Flipkart/Blinkit/Zepto) are untouched — they keep using
ProxyManager + proxies.txt.

If WBBSHARE_API is unset or the API fails, pick() returns None → the browser runs
direct (VPS IP), which is the correct fallback.
"""

import logging
import os
import threading

from curl_cffi import requests

logger = logging.getLogger(__name__)

_API_URL = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page_size=100"


def _to_playwright_proxy(p: dict) -> dict:
    return {
        "server": f"http://{p['proxy_address']}:{p['port']}",
        "username": p["username"],
        "password": p["password"],
    }


class ProxyPool:
    """Round-robin over sticky Webshare proxy IPs. Thread-safe. Lazy-loads once."""

    def __init__(self):
        self._proxies: list[dict] = []
        self._idx = 0
        self._loaded = False
        self._lock = threading.Lock()

    def _load(self) -> None:
        key = os.getenv("WBBSHARE_API")
        if not key:
            logger.warning("[Instamart] WBBSHARE_API not set — browser runs direct (no proxy)")
            self._loaded = True
            return
        try:
            r = requests.get(_API_URL, headers={"Authorization": f"Token {key}"}, timeout=20)
            results = r.json().get("results") or []
            self._proxies = [_to_playwright_proxy(p) for p in results if p.get("valid", True)]
            logger.info("[Instamart] loaded %d sticky proxies from Webshare", len(self._proxies))
        except Exception as e:
            logger.error("[Instamart] Webshare proxy fetch failed: %s — running direct", e)
        self._loaded = True

    def pick(self) -> dict | None:
        """Next sticky proxy round-robin, or None to run direct."""
        with self._lock:
            if not self._loaded:
                self._load()
            if not self._proxies:
                return None
            p = self._proxies[self._idx % len(self._proxies)]
            self._idx += 1
            return p
