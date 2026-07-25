"""Thread-safe proxy pool manager with round-robin selection and failure tracking."""

import logging
import os
import re
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from utils.headers import UA_POOL

load_dotenv()
logger = logging.getLogger(__name__)


class ProxyManager:
    """Manages a rotating pool of HTTP proxies with failure tracking and cooldown."""

    # Webshare "direct connection" list — all 100 discrete IPs in one page.
    _API_URL = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
    _API_REFRESH_SECS = 21600  # Re-pull every 6h so 7-day IP rotation doesn't shrink the pool.

    def __init__(self, proxy_file: str = "proxies.txt") -> None:
        self._lock = threading.Lock()
        self.active_pool: list[str] = []
        self.dead_pool: dict[str, float] = {}  # proxy → timestamp when it died
        self.failure_count: dict[str, int] = {}
        self.index: int = 0
        self._last_used: dict[str, float] = {}  # proxy → last time handed out (cooldown)
        # Don't reuse the same IP for Amazon within this window — spreads load so no
        # single IP gets hammered and fingerprinted in a burst. 0 disables.
        self._cooldown_secs: float = float(os.getenv("PROXY_COOLDOWN_SECS", "8"))
        self._last_revive_check: float = time.time()  # Throttle revival checks
        self._revive_check_interval: float = 30.0  # Check every 30 seconds
        self._api_key: str | None = os.getenv("WBBSHARE_API")
        self._last_api_refresh: float = time.time()
        # Cookie jar per proxy — reused across scrapes so a proxy carries a warmed
        # session forward instead of every context starting from a blank slate.
        self._proxy_cookies: dict[str, list[dict]] = {}
        # Rotating gateway (one endpoint, fresh Webshare-side IP per connection) beats
        # the 100 fixed direct IPs for Amazon: fixed IPs get burned and evicted one by
        # one until coverage collapses (not_found rate climbed 5%->46% over a week).
        # Default to the gateway from proxies.txt; set PROXY_USE_ROTATING=false to use
        # the discrete-IP API pool instead.
        self._use_rotating: bool = os.getenv("PROXY_USE_ROTATING", "true").lower() == "true"

        if self._api_key and not self._use_rotating:
            self._load_from_api()
        if not self.active_pool:
            self._load_proxies(proxy_file)

    @staticmethod
    def _parse_api_results(results: list[dict]) -> list[str]:
        """Convert Webshare API entries to http://user:pass@ip:port strings."""
        proxies = []
        for p in results:
            if not p.get("valid", True):
                continue
            proxies.append(f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}")
        return proxies

    def _load_from_api(self) -> None:
        """Fetch the current proxy list from Webshare at startup (blocking)."""
        import json
        import urllib.request

        req = urllib.request.Request(self._API_URL, headers={"Authorization": f"Token {self._api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:  # ponytail: any failure → fall back to proxy file, never crash startup
            logger.warning("Webshare API fetch failed (%s) — falling back to proxy file", e)
            return
        for proxy_url in self._parse_api_results(data.get("results", [])):
            self.active_pool.append(proxy_url)
            self.failure_count[proxy_url] = 0
        logger.info("Loaded %d proxies from Webshare API", len(self.active_pool))

    async def _refresh_from_api(self, aiohttp) -> None:
        """Re-fetch the list and add any proxies not already tracked (handles 7-day rotation)."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self._API_URL, headers={"Authorization": f"Token {self._api_key}"}, timeout=15
                ) as resp:
                    data = await resp.json()
        except Exception as e:
            logger.warning("Webshare API refresh failed: %s", e)
            return
        added = 0
        with self._lock:
            known = set(self.active_pool) | set(self.dead_pool)
            for proxy_url in self._parse_api_results(data.get("results", [])):
                if proxy_url not in known:
                    self.active_pool.append(proxy_url)
                    self.failure_count[proxy_url] = 0
                    added += 1
        if added:
            logger.info("Webshare refresh: +%d new proxies (pool now %d active)", added, len(self.active_pool))

    @staticmethod
    def _normalize_proxy(raw: str) -> str:
        """
        Convert various proxy formats to http://user:pass@ip:port.

        Supported input formats:
          - http://user:pass@ip:port  (already correct)
          - http://ip:port            (no auth)
          - ip:port:user:pass         (common residential proxy format)
          - ip:port                   (no auth, no scheme)
        """
        # Already a proper URL
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw

        parts = raw.split(":")
        if len(parts) == 4:
            # ip:port:user:pass format
            ip, port, user, passwd = parts
            return f"http://{user}:{passwd}@{ip}:{port}"
        elif len(parts) == 2:
            # ip:port format
            return f"http://{raw}"
        else:
            # Unknown format — return as-is and let it fail gracefully
            logger.warning("Unrecognized proxy format: %s", raw)
            return raw

    def _load_proxies(self, proxy_file: str) -> None:
        """Read proxies.txt line by line — skip empty lines and comments."""
        path = Path(proxy_file)
        if not path.exists():
            logger.warning("Proxy file '%s' not found — falling back to direct connections", proxy_file)
            return

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                proxy_url = self._normalize_proxy(line)
                self.active_pool.append(proxy_url)
                self.failure_count[proxy_url] = 0
                logger.debug("Loaded proxy: %s", proxy_url)

        logger.info("Loaded %d proxies from '%s'", len(self.active_pool), proxy_file)

    async def resurrect_loop(self) -> None:
        """Background task to actively test dead proxies and resurrect them if they connect successfully."""
        import aiohttp
        import asyncio
        
        while True:
            await asyncio.sleep(300)  # Every 5 minutes

            if self._api_key and not self._use_rotating and time.time() - self._last_api_refresh > self._API_REFRESH_SECS:
                await self._refresh_from_api(aiohttp)
                self._last_api_refresh = time.time()

            with self._lock:
                dead_proxies = list(self.dead_pool.keys())

            if not dead_proxies:
                continue
                
            logger.info("ProxyManager: Testing %d dead proxies for resurrection...", len(dead_proxies))
            
            async def test_proxy(proxy_url):
                # ponytail: hit amazon.in itself, not httpbin — a proxy can be alive
                # and unflagged everywhere else while Amazon specifically blocks it.
                # Still a plain aiohttp GET (no browser fingerprint), so it only catches
                # network/IP-level blocks, not the headless-fingerprint interstitial
                # bounce — upgrade to a real Playwright check if false-revivals persist.
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "https://www.amazon.in/",
                            proxy=proxy_url,
                            timeout=10,
                            headers={"User-Agent": UA_POOL[0], "Accept-Language": "en-IN,en;q=0.9"},
                        ) as resp:
                            if resp.status != 200:
                                return proxy_url, False
                            body = (await resp.text())[:2000].lower()
                            if "captcha" in body or "robot check" in body or "continue shopping" in body:
                                return proxy_url, False
                            return proxy_url, True
                except Exception:
                    pass
                return proxy_url, False
                
            results = await asyncio.gather(*(test_proxy(p) for p in dead_proxies))
            
            revived = []
            with self._lock:
                for proxy, success in results:
                    if success and proxy in self.dead_pool:
                        del self.dead_pool[proxy]
                        self.failure_count[proxy] = 0
                        if proxy not in self.active_pool:
                            self.active_pool.append(proxy)
                        revived.append(proxy)
                        
            if revived:
                logger.info("ProxyManager: Successfully resurrected %d proxies!", len(revived))

    def get_proxy(self) -> str | None:
        """Return next proxy via round-robin, skipping ones handed out within the cooldown window."""
        with self._lock:
            if not self.active_pool:
                logger.warning("Proxy pool is empty — caller should make direct request")
                return None

            now = time.time()
            pool_size = len(self.active_pool)
            for _ in range(pool_size):
                proxy = self.active_pool[self.index % pool_size]
                self.index += 1
                if now - self._last_used.get(proxy, 0) >= self._cooldown_secs:
                    self._last_used[proxy] = now
                    return proxy

            # Whole pool is within cooldown (small pool, high demand) — hand one out
            # anyway rather than starving the caller.
            proxy = self.active_pool[self.index % pool_size]
            self.index += 1
            self._last_used[proxy] = now
            return proxy

    def get_cookies(self, proxy: str | None) -> list[dict]:
        """Return the warmed cookie jar for a proxy, or [] if none saved yet."""
        if proxy is None:
            return []
        with self._lock:
            return list(self._proxy_cookies.get(proxy, []))

    def save_cookies(self, proxy: str | None, cookies: list[dict]) -> None:
        """Persist a proxy's cookie jar so the next scrape on this proxy reuses it."""
        if proxy is None or not cookies:
            return
        with self._lock:
            self._proxy_cookies[proxy] = cookies

    def report_failure(self, proxy: str) -> None:
        """Increment failure count; move to dead pool after 10 failures (unless it's the last proxy)."""
        if proxy is None:
            return

        with self._lock:
            self.failure_count[proxy] = self.failure_count.get(proxy, 0) + 1

            if self.failure_count[proxy] >= 10 and len(self.active_pool) > 1:
                if proxy in self.active_pool:
                    self.active_pool.remove(proxy)
                self.dead_pool[proxy] = time.time()
                logger.warning("Proxy moved to dead pool (failures=%d): %s", self.failure_count[proxy], proxy)
            elif self.failure_count[proxy] >= 10 and len(self.active_pool) <= 1:
                logger.warning("Proxy %s has %d failures, but it's the last one. Keeping it alive to avoid direct connection fallback.", proxy, self.failure_count[proxy])

    def report_success(self, proxy: str) -> None:
        """Reset failure count on successful use."""
        if proxy is None:
            return

        with self._lock:
            self.failure_count[proxy] = 0

    def status(self) -> dict:
        """Return pool status summary for /health endpoint."""
        with self._lock:
            return {
                "active": len(self.active_pool),
                "dead": len(self.dead_pool),
                "total": len(self.active_pool) + len(self.dead_pool),
            }

    @staticmethod
    def _mask(proxy: str) -> str:
        """Strip user:pass so the detail endpoint doesn't leak credentials."""
        return re.sub(r"//[^@]+@", "//***@", proxy)

    def detail(self) -> dict:
        """Per-proxy breakdown — failure count, cooldown state, dead-since — for the health endpoint."""
        with self._lock:
            now = time.time()
            active = [
                {
                    "proxy": self._mask(p),
                    "status": "active",
                    "failure_count": self.failure_count.get(p, 0),
                    "seconds_since_last_used": round(now - self._last_used[p], 1) if p in self._last_used else None,
                    "has_warmed_cookies": p in self._proxy_cookies,
                }
                for p in self.active_pool
            ]
            dead = [
                {
                    "proxy": self._mask(p),
                    "status": "dead",
                    "failure_count": self.failure_count.get(p, 0),
                    "dead_for_seconds": round(now - died_at, 1),
                }
                for p, died_at in self.dead_pool.items()
            ]
            return {
                "summary": {"active": len(active), "dead": len(dead), "total": len(active) + len(dead)},
                "cooldown_secs": self._cooldown_secs,
                "active_proxies": active,
                "dead_proxies": dead,
            }
