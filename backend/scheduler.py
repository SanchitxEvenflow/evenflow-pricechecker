"""Cron scheduler — periodically scrapes all ASINs from the source tab and writes to a new result tab."""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from functools import partial

from utils.scrape_helpers import CHUNK_SIZE, SCRAPE_CONCURRENCY, format_update as _format_update, BLINKIT_CITIES, format_blinkit_row
from amazon.scraper import scrape_amazon
from blinkit.scraper import fetch_blinkit_data
from blinkit.locations import LOCATIONS
from utils.google_sheets import GoogleSheetsClient
from utils import run_logger

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def _run_full_scrape(app, tab_prefix: str, run_type: str) -> None:
    """Core scrape logic shared by both automatic cron and manual trigger.

    Args:
        app: FastAPI app instance (for browser, proxy_manager, cron_status)
        tab_prefix: Prefix for the new tab name (e.g. "Run" or "Manual_Trigger")
        run_type: "automatic" or "manual" — used for logging
    """
    sheets_client = GoogleSheetsClient()
    sheet_id = os.getenv("CRON_SHEET_ID") or os.getenv("SPREADSHEET_ID", "")
    source_tab = os.getenv("CRON_SOURCE_TAB") or os.getenv("WORKSHEET_NAME", "Sheet1")

    if not sheet_id:
        logger.error("Cron: no sheet ID configured (set CRON_SHEET_ID or SPREADSHEET_ID)")
        return

    run_start = datetime.now(IST)
    logger.info("Cron: starting %s scrape — sheet=%s source_tab=%s started_at=%s",
                run_type, sheet_id, source_tab, run_start.strftime("%H:%M:%S"))

    try:
        source_rows = sheets_client.get_asins_with_rows(sheet_id, source_tab)
    except Exception:
        logger.exception("Cron: failed to read ASINs from source tab")
        return

    if not source_rows:
        logger.warning("Cron: no ASINs found in source tab '%s' — skipping run", source_tab)
        return

    now = datetime.now(IST)
    new_tab = f"{tab_prefix}_{now.strftime('%Y-%m-%d_%H-%M')}"
    asins = [r["asin"] for r in source_rows]

    # Create log entry
    run_id = run_logger.create_log(run_type, len(asins))

    try:
        sheets_client.create_tab(sheet_id, new_tab)
        sheets_client.write_header_and_asins(sheet_id, new_tab, asins)
        logger.info("Cron: created tab '%s' with %d ASINs", new_tab, len(asins))
    except Exception as e:
        logger.exception("Cron: failed to create result tab '%s'", new_tab)
        app.state.cron_status.update({"is_running": False, "error": f"Failed to create tab '{new_tab}'"})
        run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
        return

    # Remap row numbers — header is row 1, ASINs start at row 2
    remapped = [{"row": i + 2, "asin": asin} for i, asin in enumerate(asins)]

    app.state.cron_status.update({
        "is_running": True,
        "last_run_at": run_start.isoformat(),
        "last_run_tab": new_tab,
        "progress": 0,
        "total": len(remapped),
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "error": None,
    })

    browser = app.state.playwright_browser
    proxy_manager = app.state.proxy_manager
    sem = asyncio.Semaphore(SCRAPE_CONCURRENCY)

    async def scrape_one(row_data: dict) -> dict:
        async with sem:
            result = await scrape_amazon(row_data["asin"], browser, proxy_manager)
            result["row"] = row_data["row"]
            return result

    total_processed = 0
    total_success = 0
    total_failed = 0

    for chunk_start in range(0, len(remapped), CHUNK_SIZE):
        chunk = remapped[chunk_start : chunk_start + CHUNK_SIZE]
        try:
            chunk_results = await asyncio.gather(*[scrape_one(r) for r in chunk])
            updates = [_format_update(res) for res in chunk_results]
            sheets_client.batch_update_rows(sheet_id, new_tab, updates)
            total_processed += len(chunk_results)

            # Count successes/failures
            for res in chunk_results:
                status = res.get("status", "error")
                if status in ("error", "not_found", "blocked", "invalid_format"):
                    total_failed += 1
                else:
                    total_success += 1

            app.state.cron_status["progress"] = total_processed
            run_logger.update_progress(run_id, total_success, total_failed)
            logger.info("Cron: wrote chunk %d–%d to tab '%s' (%d/%d done)",
                        chunk[0]["row"], chunk[-1]["row"], new_tab, total_processed, len(remapped))
        except Exception:
            logger.exception("Cron: chunk write failed at offset %d — continuing", chunk_start)

    elapsed = datetime.now(IST) - run_start
    minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
    logger.info("Cron: run complete — %d/%d ASINs written to tab '%s' | total time: %dm %ds",
                total_processed, len(remapped), new_tab, minutes, seconds)

    app.state.cron_status.update({
        "is_running": False,
        "last_run_duration_seconds": int(elapsed.total_seconds()),
        "last_run_processed": total_processed,
        "progress": total_processed,
    })

    run_logger.complete_log(run_id, total_success, total_failed, new_tab)


async def run_scheduled_scrape(app) -> None:
    """Called by APScheduler on cron intervals."""
    await _run_full_scrape(app, tab_prefix="Run", run_type="automatic")


async def run_manual_trigger(app) -> None:
    """Called when user manually triggers the full scrape from the UI."""
    await _run_full_scrape(app, tab_prefix="Manual_Trigger", run_type="manual")


async def _run_full_blinkit_scrape(app, tab_prefix: str, run_type: str) -> None:
    """Core scrape logic for Blinkit sheet-based runs.

    Reads PIDs from BLINKIT_SHEET_ID / BLINKIT_SOURCE_TAB, scrapes all 10 cities
    per PID, and writes a wide-format result tab.
    """
    sheets_client = GoogleSheetsClient()
    sheet_id = os.getenv("BLINKIT_SHEET_ID", "")
    source_tab = os.getenv("BLINKIT_SOURCE_TAB", "Sheet1")

    if not sheet_id:
        logger.error("Blinkit: no sheet ID configured (set BLINKIT_SHEET_ID)")
        return

    run_start = datetime.now(IST)
    logger.info("Blinkit: starting %s scrape — sheet=%s source_tab=%s started_at=%s",
                run_type, sheet_id, source_tab, run_start.strftime("%H:%M:%S"))

    try:
        source_rows = sheets_client.get_asins_with_rows(sheet_id, source_tab)
    except Exception:
        logger.exception("Blinkit: failed to read PIDs from source tab")
        return

    if not source_rows:
        logger.warning("Blinkit: no PIDs found in source tab '%s' — skipping", source_tab)
        return

    now = datetime.now(IST)
    new_tab = f"{tab_prefix}_{now.strftime('%Y-%m-%d_%H-%M')}"
    pids = [r["asin"] for r in source_rows]  # get_asins_with_rows uses "asin" key
    total_combinations = len(pids) * len(LOCATIONS)

    run_id = run_logger.create_log(run_type, total_combinations)

    try:
        sheets_client.create_tab(sheet_id, new_tab)
        sheets_client.write_blinkit_header_and_pids(sheet_id, new_tab, pids)
        logger.info("Blinkit: created tab '%s' with %d PIDs (%d total combinations)",
                    new_tab, len(pids), total_combinations)
    except Exception as e:
        logger.exception("Blinkit: failed to create result tab '%s'", new_tab)
        app.state.blinkit_cron_status.update({"is_running": False, "error": f"Failed to create tab '{new_tab}'"})
        run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
        return

    app.state.blinkit_cron_status.update({
        "is_running": True,
        "last_run_at": run_start.isoformat(),
        "last_run_tab": new_tab,
        "progress": 0,
        "total": total_combinations,
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "error": None,
    })

    proxy_manager = app.state.proxy_manager
    sem = asyncio.Semaphore(5)  # Blinkit rate-limits aggressively
    loop = asyncio.get_event_loop()

    async def scrape_one_city(pid: str, loc: dict) -> dict:
        async with sem:
            proxy = proxy_manager.get_proxy()
            result = await loop.run_in_executor(
                None,
                partial(
                    fetch_blinkit_data,
                    item_id=pid,
                    pincode=loc["pincode"],
                    lat=loc["lat"],
                    lon=loc["lng"],
                    city=loc["name"],
                    proxy=proxy,
                ),
            )
            if result.get("status") == "error":
                proxy_manager.report_failure(proxy)
            else:
                proxy_manager.report_success(proxy)
            return result

    # Build all work items: pid × city
    work_items = [(pid, loc) for pid in pids for loc in LOCATIONS]
    tasks = [scrape_one_city(pid, loc) for pid, loc in work_items]

    # Gather all results while tracking progress
    results_by_pid: dict[str, dict] = {pid: {} for pid in pids}
    total_done = 0
    total_success = 0
    total_failed = 0

    for coro in asyncio.as_completed(tasks):
        result = await coro
        pid = result.get("product_id", "")
        city = result.get("city", "")
        if pid and city:
            results_by_pid[pid][city] = result

        total_done += 1
        status = result.get("status", "error")
        if status in ("error",):
            total_failed += 1
        else:
            total_success += 1

        app.state.blinkit_cron_status["progress"] = total_done
        if total_done % 10 == 0 or total_done == total_combinations:
            run_logger.update_progress(run_id, total_success, total_failed)

    logger.info("Blinkit: all %d combinations scraped — writing to sheet", total_combinations)

    # Write all rows to sheet: row 2 = pids[0], row 3 = pids[1], ...
    sheet_updates = []
    for i, pid in enumerate(pids):
        city_results = results_by_pid.get(pid, {})
        sheet_updates.append({
            "row": i + 2,
            "values": format_blinkit_row(city_results),
        })

    try:
        sheets_client.batch_update_blinkit_rows(sheet_id, new_tab, sheet_updates)
        logger.info("Blinkit: wrote %d rows to tab '%s'", len(sheet_updates), new_tab)
    except Exception:
        logger.exception("Blinkit: sheet write failed")

    elapsed = datetime.now(IST) - run_start
    minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
    logger.info("Blinkit: run complete — %d PIDs, %d cities each | tab '%s' | time: %dm %ds",
                len(pids), len(LOCATIONS), new_tab, minutes, seconds)

    app.state.blinkit_cron_status.update({
        "is_running": False,
        "last_run_duration_seconds": int(elapsed.total_seconds()),
        "last_run_processed": total_done,
        "progress": total_done,
    })

    run_logger.complete_log(run_id, total_success, total_failed, new_tab)


async def run_manual_blinkit_trigger(app) -> None:
    """Called when user manually triggers the Blinkit full scrape from the UI."""
    await _run_full_blinkit_scrape(app, tab_prefix="Blinkit_Manual", run_type="blinkit_manual")


def setup_scheduler(app) -> AsyncIOScheduler | None:
    if os.getenv("CRON_ENABLED", "false").lower() != "true":
        return None

    interval_minutes = int(os.getenv("CRON_INTERVAL_MINUTES", "60"))
    scheduler = AsyncIOScheduler()

    job_kwargs: dict = {
        "args": [app],
        "id": "scheduled_scrape",
        "max_instances": 1,
        "coalesce": True,
    }

    if interval_minutes < 60:
        # e.g. 30 → fires at :00 and :30 of every hour
        trigger = "cron"
        job_kwargs["minute"] = f"*/{interval_minutes}"
    elif interval_minutes % 60 == 0:
        # e.g. 60 → 4:00, 5:00, 6:00 | 120 → 4:00, 6:00, 8:00
        trigger = "cron"
        job_kwargs["hour"] = f"*/{interval_minutes // 60}"
        job_kwargs["minute"] = 0
    else:
        # non-round interval — fall back to relative interval trigger
        trigger = "interval"
        job_kwargs["minutes"] = interval_minutes

    scheduler.add_job(run_scheduled_scrape, trigger, **job_kwargs)
    scheduler.start()
    return scheduler
