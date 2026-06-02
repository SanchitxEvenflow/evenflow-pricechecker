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

    def _revive_dead_proxies(self) -> None:
        """Move dead proxies back to active if cooldown (600s) has passed. Must be called under lock."""
        now = time.time()
        revived: list[str] = []
        for proxy, died_at in list(self.dead_pool.items()):
            if now - died_at > 600:
                revived.append(proxy)

        for proxy in revived:
            del self.dead_pool[proxy]
            self.failure_count[proxy] = 0
            self.active_pool.append(proxy)
            logger.info("Revived proxy after cooldown: %s", proxy)

    def get_proxy(self) -> str | None:
        """Return next proxy via round-robin, or None if pool is empty."""
        with self._lock:
            self._revive_dead_proxies()

            if not self.active_pool:
                logger.warning("Proxy pool is empty — caller should make direct request")
                return None

            proxy = self.active_pool[self.index % len(self.active_pool)]
            self.index += 1
            return proxy

    def report_failure(self, proxy: str) -> None:
        """Increment failure count; move to dead pool after 2 failures."""
        if proxy is None:
            return

        with self._lock:
            self.failure_count[proxy] = self.failure_count.get(proxy, 0) + 1

            if self.failure_count[proxy] >= 2:
                if proxy in self.active_pool:
                    self.active_pool.remove(proxy)
                self.dead_pool[proxy] = time.time()
                logger.warning("Proxy moved to dead pool (failures=%d): %s", self.failure_count[proxy], proxy)

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
