"""
proxy/socks5_provider.py
SOCKS5 proxy provider for scraping via Snowpad.

Moved from instamart/socks5_provider.py — this is a shared resource used by
both Amazon and Instamart scrapers.  It belongs in the proxy package, not
under any specific platform.

Why SOCKS5 over HTTP proxies (per Snowpad docs):
  - Operates at OSI Layer 5 (Session), not Layer 7 (Application).
  - ~10 bytes overhead vs 280+ for HTTP proxies — 25-35% faster for high-volume scraping.
  - No header parsing/modification that leaks proxy fingerprints to WAF.
  - DNS resolution via the proxy (socks5h://) prevents location leaks from ISP DNS.
  - Protocol-agnostic: handles TCP, UDP, WebSockets without extra config.

Architecture:
  - Snowpad rotating endpoint: gw.snowpad.io:9999 — single auth, fresh IP per connection.
  - curl_cffi (scraper.py): uses  socks5h://user:pass@gw.snowpad.io:9999
  - Playwright (browser_scraper.py): uses {"server": "socks5://...", "username": ..., "password": ...}

Environment variables required (set in .env):
  SNOWPAD_USER     — your Snowpad proxy username
  SNOWPAD_PASS     — your Snowpad proxy password
  SNOWPAD_HOST     — proxy gateway host   (default: gw.snowpad.io)
  SNOWPAD_PORT     — proxy gateway port   (default: 9999)
  SNOWPAD_ENABLED  — set to "true" to activate (default: false)

Sticky sessions: pass session_id to curl_url()/bridge_proxy() to pin the same
exit IP for up to ~10 minutes (Snowpad's `-session-<id>` username suffix).
Used by Instamart, whose AWS WAF binds its JS-challenge token to the solving IP.

If SNOWPAD_ENABLED is not "true" or credentials are missing, all methods
return None so callers fall back to a direct connection.
"""

import asyncio
import logging
import os
import threading

from .socks5_bridge import Socks5HttpBridge

logger = logging.getLogger(__name__)


class Socks5Provider:
    """
    Provides SOCKS5 proxy strings/dicts for scrapers.

    Thread-safe singleton pattern — instantiate once, share everywhere.
    Lazy-reads env vars so the object is safe to create at import time.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._initialized = False
        self._enabled = False
        self._user: str = ""
        self._pass: str = ""
        self._host: str = "gw.snowpad.io"
        self._port: int = 9999
        # Failure tracking
        self._fail_count: int = 0
        self._MAX_FAILS_BEFORE_WARN = 5
        # Trial plan caps concurrent connections (2) — a shared semaphore keeps every
        # caller (Amazon, Instamart, ...) under that ceiling instead of each one guessing.
        self._sem: asyncio.Semaphore | None = None
        # Separate semaphore gating actual raw SOCKS5 tunnels (see socks5_bridge.py).
        # Must NOT be the same object as _sem: _sem is held for a whole scrape flow
        # (browser context open -> extraction), while a single page load fires many
        # parallel subresource connections through the bridge — reusing _sem here
        # would deadlock once 2 flows are concurrently holding both flow-level slots.
        self._conn_sem: asyncio.Semaphore | None = None
        # Chromium can't use an authenticated SOCKS5 proxy directly, so Playwright
        # callers go through a local in-process HTTP bridge instead (see bridge_proxy()).
        # Keyed by session_id (None = default rotating bridge) so sticky-session
        # callers (Instamart) each get their own bridge/credential pair.
        self._bridges: dict[str | None, Socks5HttpBridge] = {}
        self._bridge_start_lock = asyncio.Lock()

    def _init(self) -> None:
        """Lazy-initialise from env vars (called once under lock)."""
        if self._initialized:
            return

        self._enabled = os.getenv("SNOWPAD_ENABLED", "false").lower() == "true"
        self._user = os.getenv("SNOWPAD_USER", "")
        self._pass = os.getenv("SNOWPAD_PASS", "")
        self._host = os.getenv("SNOWPAD_HOST", "gw.snowpad.io")

        try:
            self._port = int(os.getenv("SNOWPAD_PORT", "9999"))
        except ValueError:
            logger.warning("[Socks5Provider] Invalid SNOWPAD_PORT — using default 9999")
            self._port = 9999

        try:
            max_concurrency = int(os.getenv("SNOWPAD_MAX_CONCURRENCY", "2"))
        except ValueError:
            max_concurrency = 2
        self._max_concurrency = max_concurrency
        self._sem = asyncio.Semaphore(max_concurrency)
        self._conn_sem = asyncio.Semaphore(max_concurrency)

        if self._enabled and (not self._user or not self._pass):
            logger.warning(
                "[Socks5Provider] SNOWPAD_ENABLED=true but SNOWPAD_USER / SNOWPAD_PASS "
                "not set — SOCKS5 disabled, falling back to direct connections."
            )
            self._enabled = False

        if self._enabled:
            logger.info(
                "[Socks5Provider] Snowpad SOCKS5 active: %s@%s:%d",
                self._user, self._host, self._port,
            )
        else:
            logger.info("[Socks5Provider] SOCKS5 disabled — direct connections will be used.")

        self._initialized = True

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        with self._lock:
            self._init()
            return self._enabled

    def curl_url(self, session_id: str | None = None) -> str | None:
        """
        Return a socks5h:// URL string for curl_cffi proxies dict.

        Uses socks5h:// (not socks5://) so DNS is resolved via the proxy —
        prevents location leaks and geo-mismatch on Indian e-commerce sites.

        Pass session_id to pin the same exit IP for ~10 minutes (Snowpad
        sticky session via `-session-<id>` username suffix).

        Returns None if SOCKS5 is disabled.

        Usage in curl_cffi:
            proxy_url = provider.curl_url()
            proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
            session = requests.Session(impersonate="chrome124", proxies=proxies)
        """
        with self._lock:
            self._init()
            if not self._enabled:
                return None
        user = f"{self._user}-session-{session_id}" if session_id else self._user
        return f"socks5h://{user}:{self._pass}@{self._host}:{self._port}"

    def playwright_proxy(self) -> dict | None:
        """
        Return a Playwright proxy dict for browser_scraper.py's open_city_page().

        Playwright wants:
          {"server": "socks5://host:port", "username": "...", "password": "..."}

        Note: Playwright handles auth separately from the URL, so credentials
        must NOT be embedded in the server string.

        Returns None if SOCKS5 is disabled.

        Usage in browser_scraper:
            proxy = provider.playwright_proxy()
            ctx, page = await open_city_page(browser, loc, proxy=proxy)
        """
        with self._lock:
            self._init()
            if not self._enabled:
                return None
        return {
            "server": f"socks5://{self._host}:{self._port}",
            "username": self._user,
            "password": self._pass,
        }

    async def bridge_proxy(self, session_id: str | None = None) -> dict | None:
        """
        Return a Playwright proxy dict pointing at a local plain-HTTP bridge that
        tunnels through Snowpad's authenticated SOCKS5 gateway.

        Chromium/Playwright cannot use an authenticated SOCKS5 proxy directly
        (browser.new_context raises "Browser does not support socks5 proxy
        authentication"), so this lazily starts an in-process bridge
        (proxy/socks5_bridge.py) on first use and hands back a no-auth
        HTTP proxy dict — the bridge does the SOCKS5 auth on Playwright's behalf.

        Pass session_id to pin the same exit IP for ~10 minutes (Snowpad sticky
        session via `-session-<id>` username suffix) — each distinct session_id
        gets its own bridge instance/port since the credential differs.

        Returns None if SOCKS5 is disabled.
        """
        with self._lock:
            self._init()
            if not self._enabled:
                return None
            user, password, host, port = self._user, self._pass, self._host, self._port

        if session_id:
            user = f"{user}-session-{session_id}"

        if session_id not in self._bridges:
            async with self._bridge_start_lock:
                if session_id not in self._bridges:
                    bridge = Socks5HttpBridge(host, port, user, password, self._conn_sem)
                    await bridge.start()
                    self._bridges[session_id] = bridge

        return {"server": f"http://127.0.0.1:{self._bridges[session_id].port}"}

    async def acquire_slot(self) -> None:
        """Block until a concurrent-connection slot is free (see SNOWPAD_MAX_CONCURRENCY)."""
        with self._lock:
            self._init()
        await self._sem.acquire()

    def release_slot(self) -> None:
        """Release a slot acquired via acquire_slot(). Callers must pair calls 1:1."""
        self._sem.release()

    def report_failure(self) -> None:
        """
        Log SOCKS5 connection failures. Snowpad uses a rotating gateway (single
        endpoint) so we can't blacklist individual IPs —
        but we can warn loudly if failures accumulate, suggesting config issues.
        """
        with self._lock:
            self._fail_count += 1
            count = self._fail_count

        if count == self._MAX_FAILS_BEFORE_WARN:
            logger.error(
                "[Socks5Provider] %d consecutive SOCKS5 failures — check SNOWPAD credentials "
                "and gateway reachability. Scraper will continue retrying.",
                count,
            )
        elif count % 10 == 0:
            logger.warning("[Socks5Provider] %d SOCKS5 failures so far.", count)

    def report_success(self) -> None:
        """Reset failure counter on a successful scrape via SOCKS5."""
        with self._lock:
            self._fail_count = 0

    def status(self) -> dict:
        """Return status dict for health endpoints."""
        with self._lock:
            self._init()
            return {
                "provider": "snowpad_socks5",
                "enabled": self._enabled,
                "host": self._host if self._enabled else None,
                "port": self._port if self._enabled else None,
                "user": self._user if self._enabled else None,
                "fail_count": self._fail_count,
                "max_concurrency": self._max_concurrency,
            }


# Module-level singleton — import and reuse across scrapers
_provider: Socks5Provider | None = None
_provider_lock = threading.Lock()


def get_provider() -> Socks5Provider:
    """Return the shared Socks5Provider singleton."""
    global _provider
    with _provider_lock:
        if _provider is None:
            _provider = Socks5Provider()
    return _provider
