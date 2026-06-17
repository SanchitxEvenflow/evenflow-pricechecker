"""Thread-safe proxy pool manager with round-robin selection and failure tracking."""

import logging
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class ProxyManager:
    """Manages a rotating pool of HTTP proxies with failure tracking and cooldown."""

    def __init__(self, proxy_file: str = "proxies.txt") -> None:
        self._lock = threading.Lock()
        self.active_pool: list[str] = []
        self.dead_pool: dict[str, float] = {}  # proxy → timestamp when it died
        self.failure_count: dict[str, int] = {}
        self.index: int = 0
        self._last_revive_check: float = time.time()  # Throttle revival checks
        self._revive_check_interval: float = 30.0  # Check every 30 seconds

        self._load_proxies(proxy_file)

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
            
            with self._lock:
                dead_proxies = list(self.dead_pool.keys())
                
            if not dead_proxies:
                continue
                
            logger.info("ProxyManager: Testing %d dead proxies for resurrection...", len(dead_proxies))
            
            async def test_proxy(proxy_url):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get("http://httpbin.org/ip", proxy=proxy_url, timeout=10) as resp:
                            if resp.status == 200:
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
        """Return next proxy via round-robin, or None if pool is empty."""
        with self._lock:
            if not self.active_pool:
                logger.warning("Proxy pool is empty — caller should make direct request")
                return None

            proxy = self.active_pool[self.index % len(self.active_pool)]
            self.index += 1
            return proxy

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
