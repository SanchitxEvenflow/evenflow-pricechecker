"""Self-check for BrowserPoolManager.acquire() waiting out a recycle.

Regression guard for 2026-07-30: both browsers died, recycle took ~5s, and every
ASIN pulled off the queue in that window was permanently marked error because
get_browser() failed fast. Run: python test_browser_pool.py
"""

import asyncio

from utils.browser_manager import BrowserPoolManager


class _FakeBrowser:
    def __init__(self, alive=True):
        self.alive = alive

    def is_connected(self):
        return self.alive


def _pool(*browsers):
    m = BrowserPoolManager.__new__(BrowserPoolManager)
    m.browsers = list(browsers)
    m.usage = [0] * len(browsers)
    m._recycling = [False] * len(browsers)
    m._index = 0
    m.max_requests = 500
    m._lock = asyncio.Lock()

    # Mirror the real _trigger_recycle: it sets the flag synchronously, which is what
    # suppresses the per-poll "Browser N is dead" log storm. The test drives revival
    # by hand instead of launching anything.
    def _trigger(idx, _b):
        m._recycling[idx] = True

    m._trigger_recycle = _trigger
    return m


async def _checks():
    live, dead = _FakeBrowser(), _FakeBrowser(alive=False)

    # Healthy pool — returns immediately.
    assert await _pool(live).acquire(timeout=1) is live

    # One slot dead, one alive: must find the live one, not raise.
    # _index starts at 0 (the dead slot), so this only passes if acquire sweeps on.
    assert await _pool(dead, live).acquire(timeout=1) is live

    # Whole pool down, recovers mid-wait — acquire must return, not error out.
    crashed = _FakeBrowser(alive=False)
    pool = _pool(crashed)

    async def revive():
        await asyncio.sleep(0.3)
        crashed.alive = True

    asyncio.ensure_future(revive())
    got = await pool.acquire(timeout=5, poll=0.05)
    assert got is crashed, got

    # Never recovers — raises after the timeout rather than hanging forever.
    started = asyncio.get_running_loop().time()
    try:
        await _pool(_FakeBrowser(alive=False)).acquire(timeout=0.4, poll=0.05)
        raise AssertionError("expected RuntimeError on timeout")
    except RuntimeError as e:
        assert "still recycling" in str(e), e
    elapsed = asyncio.get_running_loop().time() - started
    assert 0.4 <= elapsed < 2.0, elapsed

    # Empty pool is a hard error, not an infinite wait.
    try:
        await _pool().acquire(timeout=1)
        raise AssertionError("expected RuntimeError on empty pool")
    except RuntimeError as e:
        assert "not initialized" in str(e), e

    print("ok")


if __name__ == "__main__":
    asyncio.run(_checks())
