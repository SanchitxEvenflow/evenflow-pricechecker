"""Run with backend dependencies installed: python backend/test_scrape_recovery.py."""

import asyncio
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import scheduler
from amazon.scraper import _detect_status
from bs4 import BeautifulSoup
from flipkart.scraper import _extract_from_rome
from utils.google_sheets import GoogleSheetsClient
from test_qc_retries import _Snowpad


async def check_journal():
    with TemporaryDirectory() as directory, patch.dict(os.environ, {"SHEETS_OUTBOX_DIR": directory}):
        client = GoogleSheetsClient.__new__(GoogleSheetsClient)
        client.batch_update_rows = Mock(side_effect=OSError("Sheets offline"))
        updates = [{"row": 2, "values": ["99", "available"]}]
        try:
            await client.async_batch_update_rows("sheet", "tab", updates)
        except OSError:
            pass
        else:
            raise AssertionError("failed upload reported success")
        assert len(list(Path(directory).glob("*.json"))) == 1

        # A new client represents restart; no in-memory result state is available.
        restarted = GoogleSheetsClient.__new__(GoogleSheetsClient)
        restarted.batch_update_rows = Mock()
        await asyncio.to_thread(restarted.replay_pending_writes)
        restarted.batch_update_rows.assert_called_once_with("sheet", "tab", updates)
        assert not list(Path(directory).glob("*.json"))

        # Older failed writes must replay before a newer value for the same row.
        try:
            await client.async_batch_update_rows("sheet", "tab", updates)
        except OSError:
            pass
        newer = [{"row": 2, "values": ["100", "available"]}]
        await restarted.async_batch_update_rows("sheet", "tab", newer)
        assert restarted.batch_update_rows.call_args_list[-2].args[-1] == updates
        assert restarted.batch_update_rows.call_args_list[-1].args[-1] == newer


async def check_qc_checkpoints(platform):
    saved = []
    sheets = Mock()
    sheets.get_asins_with_rows.return_value = [{"asin": str(n)} for n in range(60)]

    async def write(_sheet, _tab, updates):
        saved.append([u["row"] for u in updates])

    setattr(sheets, f"async_batch_update_{platform}_rows", write)
    state = SimpleNamespace(
        sheets_client=sheets, thread_pool=None,
        browser_manager=SimpleNamespace(browsers=[object()], acquire=AsyncMock(return_value=object())),
        batch_throttle=asyncio.Semaphore(2), total_sem=asyncio.Semaphore(2),
    )
    setattr(state, f"{platform}_cron_status", {})
    loc = {"name": "Bangalore", "pincode": "560102", "lat": 1, "lng": 2}
    batches = 0

    def results(pids, city):
        nonlocal batches
        if batches:
            assert len(saved) == batches, "next chunk scraped before checkpoint"
        batches += 1
        return {pid: {"product_id": pid, "city": city, "status": "available", "price": 99.0} for pid in pids}

    async def browser_sweep(_browser, loc, pids, on_result):
        out = results(pids, loc["name"])
        for pid, result in out.items():
            on_result(pid, result)
        return out

    def curl_sweep(item_ids, city, **_kwargs):
        return results(item_ids, city)

    if platform == "blinkit":
        scraper_patch = patch.object(scheduler, "fetch_blinkit_city", curl_sweep)
    else:
        scraper_patch = patch(f"{platform}.browser_scraper.sweep_city", browser_sweep)
    with patch.dict(os.environ, {f"{platform.upper()}_SHEET_ID": "sheet"}), \
         patch.object(scheduler, f"{platform.upper()}_LOCATIONS", [loc]), \
         patch.object(scheduler, "run_logger", Mock()), \
         patch.object(scheduler, "get_snowpad_provider", return_value=_Snowpad()), scraper_patch:
        await getattr(scheduler, f"_run_full_{platform}_scrape")(
            SimpleNamespace(state=state), tab_prefix="Test", run_type="manual",
        )
    assert [len(batch) for batch in saved] == [25, 25, 10], saved
    assert [row for batch in saved for row in batch] == list(range(2, 62))
    assert getattr(state, f"{platform}_cron_status")["last_run_processed"] == 60


async def check_amazon_cancel_and_resume():
    sheets = Mock()
    sheets.get_asins_with_rows.return_value = [{"asin": "B012345678"}, {"asin": "B012345679"}]
    sheets.async_batch_update_rows = AsyncMock()
    state = SimpleNamespace(sheets_client=sheets, cron_status={}, browser_manager=object())
    app = SimpleNamespace(state=state)
    state.batch_throttle = asyncio.Semaphore(1)
    state.total_sem = asyncio.Semaphore(1)

    async def scrape(asin, *_args, **_kwargs):
        if asin.endswith("9"):
            await asyncio.Event().wait()
        return {"asin": asin, "status": "available", "price": "99"}

    logs = Mock()
    with patch.dict(os.environ, {"CRON_SHEET_ID": "sheet"}), \
         patch.object(scheduler, "run_logger", logs), \
         patch.object(scheduler, "get_browser", AsyncMock(return_value=object())), \
         patch.object(scheduler, "scrape_amazon_with_retry", scrape):
        task = asyncio.create_task(scheduler._run_full_scrape(app, "Test", "automatic"))
        try:
            async with asyncio.timeout(2):
                while state.cron_status.get("progress", 0) < 1:
                    await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert sheets.async_batch_update_rows.await_args.args[-1][0]["row"] == 2
        assert logs.fail_log.call_args.kwargs["resumable"] is True
        logs.complete_log.assert_not_called()
        logs.get_all_logs.return_value = [{
            "run_id": "old", "type": "automatic", "status": "failed",
            "resumable": True, "sheet_tab": "Test",
        }]
        with patch.object(scheduler, "_run_full_scrape", AsyncMock()) as resume:
            await scheduler.resume_interrupted_scrape(app)
            sheets.replay_pending_writes.assert_called_once()
            assert resume.await_args.kwargs["resume_tab"] == "Test"


async def check_manual_amazon_skips_metadata_request():
    sheets = Mock()
    sheets.get_asins_with_rows.return_value = [{"asin": "B012345678"}]
    sheets.async_batch_update_rows = AsyncMock()
    state = SimpleNamespace(
        sheets_client=sheets, cron_status={}, browser_manager=object(),
        batch_throttle=asyncio.Semaphore(1), total_sem=asyncio.Semaphore(1),
    )

    async def scrape(asin, *_args, **_kwargs):
        return {"asin": asin, "status": "available", "price": "99", "_cookies": {"sid": "x"}}

    supplement = AsyncMock()
    with patch.dict(os.environ, {"CRON_SHEET_ID": "sheet"}), \
         patch.object(scheduler, "run_logger", Mock()), \
         patch.object(scheduler, "get_browser", AsyncMock(return_value=object())), \
         patch.object(scheduler, "scrape_amazon_with_retry", scrape), \
         patch.object(scheduler, "fetch_curl_supplement", supplement):
        await scheduler._run_full_scrape(
            SimpleNamespace(state=state), "Manual", "manual", write_historical=False,
        )
    supplement.assert_not_awaited()
    assert sheets.async_batch_update_rows.await_args.args[-1][0]["values"][0] == "99"


def check_secondary_crons_are_opt_in():
    fake = Mock()
    with patch.dict(os.environ, {"CRON_ENABLED": "true"}, clear=False), \
         patch.object(scheduler, "AsyncIOScheduler", return_value=fake):
        os.environ.pop("AMAZON_CRON_HOUR_2", None)
        os.environ.pop("FLIPKART_CRON_HOUR_2", None)
        scheduler.setup_scheduler(object())
    job_ids = {call.kwargs["id"] for call in fake.add_job.call_args_list}
    assert "amazon_daily_scrape_2" not in job_ids
    assert "flipkart_daily_scrape_2" not in job_ids


async def main():
    await check_journal()
    for platform in ("blinkit", "zepto", "instamart"):
        await check_qc_checkpoints(platform)
    await check_amazon_cancel_and_resume()
    await check_manual_amazon_skips_metadata_request()
    check_secondary_crons_are_opt_in()
    for html, code, status in [
        ("<body>Loading</body>", 200, "blocked"),
        ("<body>Not found</body>", 404, "not_found"),
        ('<span id="productTitle">Product</span>', 200, "check_price"),
    ]:
        soup = BeautifulSoup(html, "html.parser")
        assert _detect_status(soup, soup.get_text(), "B012345678", http_status=code) == status
    incomplete_rome = {"RESPONSE": {"slots": [{
        "widget": {"type": "PRODUCT_PRICE_SUMMARY", "data": {"pricing": {"value": {}}}},
    }]}}
    assert _extract_from_rome(incomplete_rome) is None
    print("scrape recovery checks passed")


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    asyncio.run(main())
