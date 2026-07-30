import asyncio
import logging

logger = logging.getLogger(__name__)


class BrowserPoolManager:
    def __init__(
        self,
        playwright_instance,
        pool_size: int,
        headless: bool,
        args: list[str],
        max_requests: int = 500,
        executable_path: str | None = None,
    ):
        self.playwright = playwright_instance
        self.pool_size = pool_size
        self.headless = headless
        self.args = args
        self.max_requests = max_requests
        self.executable_path = executable_path

        self.browsers: list = []
        self.usage: list[int] = []
        self._recycling: list[bool] = []   # True while a recycle is in-flight for that slot
        self._index = 0
        self._lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None

    # ── Launch ───────────────────────────────────────────────────────────────

    async def launch_all(self):
        for i in range(self.pool_size):
            try:
                logger.info(
                    "BrowserPool: launching %d/%d | exe=%s | headless=%s",
                    i + 1, self.pool_size,
                    self.executable_path or "(playwright bundled)",
                    self.headless,
                )
                b = await self._launch_one()
                self.browsers.append(b)
                self.usage.append(0)
                self._recycling.append(False)
                logger.info("BrowserPool: Browser %d/%d launched", i + 1, self.pool_size)
            except Exception as e:
                logger.error("BrowserPool: Failed to launch browser %d: %s", i + 1, e)

        # Start background health monitor (checks every 60 s)
        self._monitor_task = asyncio.create_task(self._health_monitor())

    async def _launch_one(self):
        return await self.playwright.chromium.launch(
            headless=self.headless,
            args=self.args,
            executable_path=self.executable_path,
        )

    # ── Get browser ──────────────────────────────────────────────────────────

    def get_browser(self):
        """Return the next browser in the round-robin pool.

        If the selected browser is dead (not connected), a background recycle
        is triggered and RuntimeError is raised so the caller can fail fast
        instead of attempting a doomed new_context() call.
        """
        if not self.browsers:
            return None

        idx = self._index
        self._index = (self._index + 1) % len(self.browsers)

        b = self.browsers[idx]

        # ── Liveness check ──
        if not b.is_connected():
            # Only log on the call that actually starts the recycle — a dead pool can be
            # polled hundreds of times per second, and every one of those used to log.
            if not self._recycling[idx]:
                logger.warning(
                    "BrowserPool: Browser %d is dead (is_connected=False) — triggering recycle", idx
                )
            self._trigger_recycle(idx, b)
            raise RuntimeError(
                f"Browser {idx} has crashed and is being recycled — retry shortly"
            )

        self.usage[idx] += 1

        if self.usage[idx] >= self.max_requests:
            self.usage[idx] = 0
            logger.info(
                "BrowserPool: Browser %d hit request limit (%d) — scheduling recycle",
                idx, self.max_requests,
            )
            self._trigger_recycle(idx, b)

        return b

    async def acquire(self, timeout: float = 45.0, poll: float = 0.5):
        """Return a live browser, waiting out an in-flight recycle.

        get_browser() fails fast, which is right for a scrape already holding a
        page. It is wrong for a caller that has just picked up a work item: a
        recycle takes a few seconds, and failing fast burns every ASIN pulled off
        the queue during that window. This polls all slots until one comes back.
        """
        if not self.browsers:
            raise RuntimeError("Browser pool not initialized — Playwright failed to start")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        waited = False

        while True:
            # One pass over every slot — with pool size 2, slot 0 can be dead while 1 is fine.
            for _ in range(len(self.browsers)):
                try:
                    return self.get_browser()
                except RuntimeError:
                    continue

            if loop.time() >= deadline:
                raise RuntimeError(
                    f"No live browser after {timeout:.0f}s — pool still recycling"
                )

            if not waited:
                waited = True
                logger.warning(
                    "BrowserPool: all %d browsers down — waiting up to %.0fs for recycle",
                    len(self.browsers), timeout,
                )
            await asyncio.sleep(poll)

    # ── External dead-browser notification ───────────────────────────────────

    def notify_dead(self, browser) -> None:
        """Called by a scraper that received TargetClosedError on this browser.

        Finds the browser in the pool and triggers a recycle if one isn't
        already in-flight.
        """
        try:
            idx = self.browsers.index(browser)
        except ValueError:
            return  # already recycled / replaced

        if not self._recycling[idx]:
            logger.warning(
                "BrowserPool: notify_dead() for browser %d — triggering recycle", idx
            )
            self._trigger_recycle(idx, browser)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _trigger_recycle(self, idx: int, old_b) -> None:
        """Fire-and-forget recycle task, guarded against concurrent recycles."""
        if self._recycling[idx]:
            return  # already recycling this slot
        self._recycling[idx] = True
        asyncio.create_task(self._recycle(idx, old_b))

    async def _recycle(self, idx: int, old_b) -> None:
        try:
            async with self._lock:
                # Double-check: another task may have already replaced this slot
                if self.browsers[idx] is not old_b:
                    logger.info("BrowserPool: Slot %d already replaced — skipping recycle", idx)
                    return

                logger.info("BrowserPool: Recycling browser %d ...", idx)
                new_b = await self._launch_one()
                self.browsers[idx] = new_b
                self.usage[idx] = 0
                logger.info("BrowserPool: Browser %d recycled successfully", idx)

            # Close the old browser outside the lock so we don't block other recycles
            try:
                await old_b.close()
            except Exception:
                pass  # already dead — ignore

        except Exception as e:
            logger.error("BrowserPool: Failed to recycle browser %d: %s", idx, e)
        finally:
            self._recycling[idx] = False

    # ── Background health monitor ─────────────────────────────────────────────

    async def _health_monitor(self) -> None:
        """Every 60 s, scan all pool slots and recycle any dead browser."""
        while True:
            await asyncio.sleep(60)
            for idx, b in enumerate(self.browsers):
                try:
                    if not b.is_connected():
                        logger.warning(
                            "BrowserPool: Health monitor detected dead browser %d — recycling", idx
                        )
                        self._trigger_recycle(idx, b)
                except Exception as e:
                    logger.warning("BrowserPool: Health monitor error for browser %d: %s", idx, e)

    # ── Shutdown ──────────────────────────────────────────────────────────────

    async def close_all(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()
        for b in self.browsers:
            try:
                await b.close()
            except Exception:
                pass
        self.browsers.clear()
        self.usage.clear()
        self._recycling.clear()
