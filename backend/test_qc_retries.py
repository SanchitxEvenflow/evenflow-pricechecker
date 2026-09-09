"""Self-check for exact-once QC sweep retries. Run: python test_qc_retries.py"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from blinkit import scraper as blinkit
from instamart import browser_scraper as instamart
from zepto import browser_scraper as zepto
from utils.scrape_helpers import unique_queue_results


class _Page:
    async def wait_for_timeout(self, _milliseconds):
        pass


class _Snowpad:
    def __init__(self):
        self.acquired = 0
        self.released = 0

    async def acquire_slot(self):
        self.acquired += 1

    def release_slot(self):
        self.released += 1

    async def close_bridge(self, _session_id):
        pass


async def _check(module):
    snowpad = _Snowpad()
    calls = {}
    emitted = []
    originals = (
        module.get_snowpad_provider,
        module.open_city_page,
        module.close_ctx,
        module.scrape_item,
        module._SESSION_BATCH_SIZE,
    )

    async def open_city_page(_browser, _loc, session_id=None):
        return object(), _Page()

    async def close_ctx(_ctx):
        pass

    async def scrape_item(_page, pid, city):
        calls[pid] = calls.get(pid, 0) + 1
        status = "error" if pid == "retry-me" and calls[pid] == 1 else "available"
        return {"product_id": pid, "city": city, "status": status}

    try:
        module.get_snowpad_provider = lambda: snowpad
        module.open_city_page = open_city_page
        module.close_ctx = close_ctx
        module.scrape_item = scrape_item
        module._SESSION_BATCH_SIZE = 100

        results = await module.sweep_city(
            object(), {"name": "Bangalore"}, ["ok", "retry-me", "ok"],
            on_result=lambda pid, result: emitted.append((pid, result["status"])),
        )
        assert results["retry-me"]["status"] == "available", results
        assert calls == {"ok": 1, "retry-me": 2}, calls
        assert emitted == [("ok", "available"), ("retry-me", "available")], emitted
        assert snowpad.acquired == snowpad.released == 1, (snowpad.acquired, snowpad.released)
    finally:
        (
            module.get_snowpad_provider,
            module.open_city_page,
            module.close_ctx,
            module.scrape_item,
            module._SESSION_BATCH_SIZE,
        ) = originals


def _check_blinkit():
    calls = {}
    emitted = []
    originals = (
        blinkit.get_snowpad_provider,
        blinkit.requests.Session,
        blinkit._fetch_once,
        blinkit.BLINKIT_SESSION_BATCH_SIZE,
    )

    class Cookies:
        def set(self, *_args, **_kwargs):
            pass

    class Session:
        cookies = Cookies()

        def get(self, *_args, **_kwargs):
            return type("Response", (), {"status_code": 200})()

        def close(self):
            pass

    class Snowpad:
        enabled = False

        def report_success(self):
            pass

        def report_failure(self):
            pass

    def fetch_once(_session, pid, _pincode, _lat, _lon, city):
        calls[pid] = calls.get(pid, 0) + 1
        status = "error" if pid == "retry-me" and calls[pid] == 1 else "available"
        return {"product_id": pid, "city": city, "status": status}

    try:
        blinkit.get_snowpad_provider = Snowpad
        blinkit.requests.Session = lambda **_kwargs: Session()
        blinkit._fetch_once = fetch_once
        blinkit.BLINKIT_SESSION_BATCH_SIZE = 100
        results = blinkit.fetch_blinkit_city(
            ["ok", "retry-me", "ok"], "560102", 1.0, 2.0, "Bangalore",
            on_result=lambda pid, result: emitted.append((pid, result["status"])),
        )
        assert results["retry-me"]["status"] == "available", results
        assert calls == {"ok": 1, "retry-me": 2}, calls
        assert emitted == [("ok", "available"), ("retry-me", "available")], emitted
    finally:
        (
            blinkit.get_snowpad_provider,
            blinkit.requests.Session,
            blinkit._fetch_once,
            blinkit.BLINKIT_SESSION_BATCH_SIZE,
        ) = originals


async def demo():
    await _check(zepto)
    await _check(instamart)
    _check_blinkit()
    for module in (zepto, instamart):
        await _check_bulk_recovery(module)
        await _check_item_timeout(module)
    await _check_missing_data()

    queue = asyncio.Queue()

    async def partial_worker():
        await queue.put({"product_id": "a", "city": "X", "status": "available"})
        await queue.put({"product_id": "a", "city": "X", "status": "error"})
        await queue.put({"product_id": "b", "city": "X", "status": "available"})

    task = asyncio.create_task(partial_worker())
    expected = {(pid, "X") for pid in ("a", "b", "c")}
    results = [
        result async for result in unique_queue_results(queue, [task], expected, timeout=0.01)
        if result is not None
    ]
    assert [(r["product_id"], r["city"]) for r in results] == [("a", "X"), ("b", "X"), ("c", "X")]
    assert results[-1]["status"] == "error"
    print("ok")


async def _check_bulk_recovery(module):
    """Reproduce 90/100 plus a failed second session setup."""
    snowpad = _Snowpad()
    calls, emitted = {}, []
    opens = 0

    async def open_page(*_args, **_kwargs):
        nonlocal opens
        opens += 1
        # Exhaust setup retries at PID 25: the next PID must still be attempted.
        if 2 <= opens <= 4:
            raise RuntimeError("temporary setup failure")
        return object(), _Page()

    async def scrape(_page, pid, city):
        calls[pid] = calls.get(pid, 0) + 1
        status = "error" if int(pid) >= 90 and calls[pid] == 1 else "available"
        return {"product_id": pid, "city": city, "status": status}

    with patch.object(module, "get_snowpad_provider", return_value=snowpad), \
         patch.object(module, "open_city_page", open_page), \
         patch.object(module, "close_ctx", AsyncMock()), \
         patch.object(module, "scrape_item", scrape), \
         patch.object(module, "_SESSION_BATCH_SIZE", 25), \
         patch.object(asyncio, "sleep", AsyncMock()):
        results = await module.sweep_city(
            object(), {"name": "X"}, [str(n) for n in range(100)],
            on_result=lambda pid, r: emitted.append(pid),
        )
    assert len(calls) == len(results) == len(set(emitted)) == len(emitted) == 100
    assert all(r["status"] == "available" for r in results.values())
    assert snowpad.acquired == snowpad.released == 1


async def _check_item_timeout(module):
    snowpad = _Snowpad()
    calls = {}

    async def scrape(_page, pid, city):
        calls[pid] = calls.get(pid, 0) + 1
        if pid == "stuck":
            await asyncio.Event().wait()
        return {"product_id": pid, "city": city, "status": "available"}

    platform = module.__name__.split(".")[0].upper()
    with patch.dict(os.environ, {f"{platform}_ITEM_TIMEOUT_SECONDS": "0.01"}), \
         patch.object(module, "get_snowpad_provider", return_value=snowpad), \
         patch.object(module, "open_city_page", AsyncMock(return_value=(object(), _Page()))), \
         patch.object(module, "close_ctx", AsyncMock()), \
         patch.object(module, "scrape_item", scrape):
        results = await module.sweep_city(object(), {"name": "X"}, ["stuck", "ok"])
    assert results["stuck"]["status"] == "error"
    assert calls == {"stuck": 2, "ok": 1}
    assert results["ok"]["status"] == "available"
    assert snowpad.acquired == snowpad.released == 1


async def _check_missing_data():
    page = SimpleNamespace(
        content=AsyncMock(return_value='<script>{"product":{"name":"Product"}}</script>'),
        wait_for_timeout=AsyncMock(),
    )
    with patch.object(zepto, "_goto_ok", AsyncMock(return_value=SimpleNamespace(status=200))):
        assert (await zepto.scrape_item(page, "pid", "X"))["status"] == "error"
    locator = SimpleNamespace(count=AsyncMock(return_value=0))
    locator.first = locator
    page = SimpleNamespace(
        locator=lambda *_args: locator, title=AsyncMock(return_value="Product"),
        inner_text=AsyncMock(return_value="Loading"),
    )
    with patch.object(instamart, "_goto_ok", AsyncMock(return_value=True)), \
         patch.object(instamart, "_testid_text", AsyncMock(return_value=None)):
        assert (await instamart.scrape_item(page, "pid", "X"))["status"] == "error"
        locator.count.return_value = 1  # ADD button alone does not prove out-of-stock.
        locator.text_content = AsyncMock(return_value="Product")
        assert (await instamart.scrape_item(page, "pid", "X"))["status"] == "error"
        locator.count.return_value = 0
        page.inner_text.return_value = "Sold out"
        assert (await instamart.scrape_item(page, "pid", "X"))["status"] == "out_of_stock"


if __name__ == "__main__":
    asyncio.run(demo())
