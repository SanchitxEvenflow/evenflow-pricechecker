import asyncio
import logging

logger = logging.getLogger(__name__)

class BrowserPoolManager:
    def __init__(self, playwright_instance, pool_size: int, headless: bool, args: list[str], max_requests: int = 500):
        self.playwright = playwright_instance
        self.pool_size = pool_size
        self.headless = headless
        self.args = args
        self.max_requests = max_requests
        
        self.browsers = []
        self.usage = []
        self._index = 0
        self._lock = asyncio.Lock()

    async def launch_all(self):
        for i in range(self.pool_size):
            try:
                b = await self.playwright.chromium.launch(headless=self.headless, args=self.args)
                self.browsers.append(b)
                self.usage.append(0)
                logger.info("BrowserPool: Browser %d/%d launched", i + 1, self.pool_size)
            except Exception as e:
                logger.error("BrowserPool: Failed to launch browser %d: %s", i + 1, e)

    def get_browser(self):
        if not self.browsers:
            return None
            
        idx = self._index
        self._index = (self._index + 1) % len(self.browsers)
        
        b = self.browsers[idx]
        self.usage[idx] += 1
        
        if self.usage[idx] >= self.max_requests:
            self.usage[idx] = 0
            logger.info("BrowserPool: Browser %d hit request limit (%d). Scheduling background recycle...", idx, self.max_requests)
            asyncio.create_task(self._recycle(idx, b))
            
        return b

    async def _recycle(self, idx: int, old_b):
        async with self._lock:
            try:
                new_b = await self.playwright.chromium.launch(headless=self.headless, args=self.args)
                self.browsers[idx] = new_b
                logger.info("BrowserPool: Successfully launched replacement browser for index %d", idx)
                
                # Wait 30 seconds to let existing contexts on the old browser gracefully finish
                await asyncio.sleep(30)
                await old_b.close()
                logger.info("BrowserPool: Closed old browser for index %d", idx)
            except Exception as e:
                logger.error("BrowserPool: Failed to recycle browser %d: %s", idx, e)

    async def close_all(self):
        for b in self.browsers:
            try:
                await b.close()
            except Exception:
                pass
        self.browsers.clear()
        self.usage.clear()
