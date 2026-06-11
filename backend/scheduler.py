"""Cron scheduler — periodically scrapes all ASINs from the source tab and writes to a new result tab."""

import asyncio
import logging
import os
import random
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils.scrape_helpers import (
    batch_context,
    CHUNK_SIZE,
    format_update as _format_update,
    format_flipkart_update as _format_flipkart_update,
    BLINKIT_CITIES,
    format_blinkit_row,
    ZEPTO_CITIES,
    format_zepto_row,
    INSTAMART_CITIES,
    format_instamart_row,
    get_browser,
)

from amazon.scraper import scrape_amazon
from flipkart.scraper import scrape_flipkart
from blinkit.scraper import fetch_blinkit_data
from blinkit.locations import LOCATIONS as BLINKIT_LOCATIONS
from zepto.scraper import fetch_zepto_data
from zepto.locations import LOCATIONS as ZEPTO_LOCATIONS
from instamart.locations import LOCATIONS as INSTAMART_LOCATIONS
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
    sheets_client = app.state.sheets_client
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

    proxy_manager = app.state.proxy_manager

    async def scrape_one(row_data: dict) -> dict:
        async with batch_context(app.state):
            result = await scrape_amazon(row_data["asin"], get_browser(app.state), proxy_manager)
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
            await sheets_client.async_batch_update_rows(sheet_id, new_tab, updates)
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
    await asyncio.sleep(0.1)
    await _run_full_scrape(app, tab_prefix="Manual_Trigger", run_type="manual")


async def _run_full_blinkit_scrape(app, tab_prefix: str, run_type: str) -> None:
    """Core scrape logic for Blinkit sheet-based runs.

    Reads PIDs from BLINKIT_SHEET_ID / BLINKIT_SOURCE_TAB, scrapes all 10 cities
    per PID, and writes a wide-format result tab.
    """
    sheets_client = app.state.sheets_client
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

    run_id = run_logger.create_log(run_type, len(pids))

    try:
        sheets_client.create_tab(sheet_id, new_tab)
        sheets_client.write_blinkit_header_and_pids(sheet_id, new_tab, pids)
        logger.info("Blinkit: created tab '%s' with %d PIDs", new_tab, len(pids))
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
        "total": len(pids),
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "error": None,
    })

    proxy_manager = app.state.proxy_manager
    sem = asyncio.Semaphore(5)  # Blinkit rate-limits aggressively
    loop = asyncio.get_running_loop()

    async def scrape_one_city(pid: str, loc: dict) -> dict:
        async with sem:
            result = await loop.run_in_executor(
                app.state.thread_pool,
                partial(
                    fetch_blinkit_data,
                    item_id=pid,
                    pincode=loc["pincode"],
                    lat=loc["lat"],
                    lon=loc["lng"],
                    city=loc["name"],
                    proxy_manager=proxy_manager,
                ),
            )
            return result

    # Process one PID at a time — all 10 cities in parallel, then delay before next PID.
    # Batch updates to sheets (max 100 per batch) to avoid N+1 API calls.
    total_done = 0
    total_success = 0
    total_failed = 0
    batch_updates = []
    BATCH_SIZE = 100  # Google Sheets API batch limit

    for i, pid in enumerate(pids):
        pid_tasks = [scrape_one_city(pid, loc) for loc in BLINKIT_LOCATIONS]
        city_results = await asyncio.gather(*pid_tasks, return_exceptions=True)

        results_by_city: dict = {}
        for result in city_results:
            if isinstance(result, Exception):
                total_failed += 1
                continue
            city = result.get("city", "")
            if city:
                results_by_city[city] = result
            status = result.get("status", "error")
            if status == "error":
                total_failed += 1
            else:
                total_success += 1

        total_done += 1
        app.state.blinkit_cron_status["progress"] = total_done
        run_logger.update_progress(run_id, total_success, total_failed)

        # Collect update for batching
        batch_updates.append({
            "row": i + 2,
            "values": format_blinkit_row(results_by_city),
        })

        # Flush batch if full or at end
        should_flush = (len(batch_updates) == BATCH_SIZE) or (i == len(pids) - 1)
        if should_flush:
            try:
                await sheets_client.async_batch_update_blinkit_rows(sheet_id, new_tab, batch_updates)
                logger.info("Blinkit: wrote batch of %d rows (%d/%d total)", 
                           len(batch_updates), total_done, len(pids))
                batch_updates = []
            except Exception:
                logger.exception("Blinkit: failed to write batch at offset %d", i - len(batch_updates))
                batch_updates = []

        if i < len(pids) - 1:
            delay = random.uniform(
                float(os.getenv("BLINKIT_DELAY_MIN", "1.0")),
                float(os.getenv("BLINKIT_DELAY_MAX", "3.0")),
            )
            await asyncio.sleep(delay)

    logger.info("Blinkit: all %d PIDs processed — tab '%s'", len(pids), new_tab)

    elapsed = datetime.now(IST) - run_start
    minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
    logger.info("Blinkit: run complete — %d PIDs × %d cities | tab '%s' | time: %dm %ds",
                len(pids), len(BLINKIT_LOCATIONS), new_tab, minutes, seconds)

    app.state.blinkit_cron_status.update({
        "is_running": False,
        "last_run_duration_seconds": int(elapsed.total_seconds()),
        "last_run_processed": len(pids),
        "progress": len(pids),
    })

    run_logger.complete_log(run_id, total_success, total_failed, new_tab)


async def run_manual_blinkit_trigger(app) -> None:
    """Called when user manually triggers the Blinkit full scrape from the UI."""
    await asyncio.sleep(0.1)
    await _run_full_blinkit_scrape(app, tab_prefix="Blinkit_Manual", run_type="blinkit_manual")


async def _run_full_zepto_scrape(app, tab_prefix: str, run_type: str) -> None:
    """Core scrape logic for Zepto sheet-based runs."""
    sheets_client = app.state.sheets_client
    sheet_id = os.getenv("ZEPTO_SHEET_ID", "")
    source_tab = os.getenv("ZEPTO_SOURCE_TAB", "Sheet1")

    if not sheet_id:
        logger.error("Zepto: no sheet ID configured (set ZEPTO_SHEET_ID)")
        return

    run_start = datetime.now(IST)
    logger.info("Zepto: starting %s scrape — sheet=%s source_tab=%s started_at=%s",
                run_type, sheet_id, source_tab, run_start.strftime("%H:%M:%S"))

    try:
        source_rows = sheets_client.get_asins_with_rows(sheet_id, source_tab)
    except Exception:
        logger.exception("Zepto: failed to read PIDs from source tab")
        return

    if not source_rows:
        logger.warning("Zepto: no PIDs found in source tab '%s' — skipping", source_tab)
        return

    now = datetime.now(IST)
    new_tab = f"{tab_prefix}_{now.strftime('%Y-%m-%d_%H-%M')}"
    pids = [r["asin"] for r in source_rows]

    run_id = run_logger.create_log(run_type, len(pids))

    try:
        sheets_client.create_tab(sheet_id, new_tab)
        sheets_client.write_zepto_header_and_pids(sheet_id, new_tab, pids)
        logger.info("Zepto: created tab '%s' with %d PIDs", new_tab, len(pids))
    except Exception as e:
        logger.exception("Zepto: failed to create result tab '%s'", new_tab)
        app.state.zepto_cron_status.update({"is_running": False, "error": f"Failed to create tab '{new_tab}'"})
        run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
        return

    app.state.zepto_cron_status.update({
        "is_running": True,
        "last_run_at": run_start.isoformat(),
        "last_run_tab": new_tab,
        "progress": 0,
        "total": len(pids),
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "error": None,
    })

    proxy_manager = app.state.proxy_manager
    sem = asyncio.Semaphore(5)
    loop = asyncio.get_running_loop()

    async def scrape_one_city(pid: str, loc: dict) -> dict:
        async with sem:
            result = await loop.run_in_executor(
                app.state.thread_pool,
                partial(
                    fetch_zepto_data,
                    item_id=pid,
                    pincode=loc["pincode"],
                    lat=loc["lat"],
                    lon=loc["lng"],
                    city=loc["name"],
                    store_id=loc["store_id"],
                    proxy_manager=proxy_manager,
                ),
            )
            return result

    total_done = 0
    total_success = 0
    total_failed = 0

    # Process one PID at a time — all 9 cities in parallel, then delay before next PID.
    # Batch updates to sheets (max 100 per batch) to avoid N+1 API calls.
    total_done = 0
    total_success = 0
    total_failed = 0
    batch_updates = []
    BATCH_SIZE = 100  # Google Sheets API batch limit

    for i, pid in enumerate(pids):
        pid_tasks = [scrape_one_city(pid, loc) for loc in ZEPTO_LOCATIONS]
        city_results = await asyncio.gather(*pid_tasks, return_exceptions=True)

        results_by_city: dict = {}
        for result in city_results:
            if isinstance(result, Exception):
                total_failed += 1
                continue
            city = result.get("city", "")
            if city:
                results_by_city[city] = result
            status = result.get("status", "error")
            if status == "error":
                total_failed += 1
            else:
                total_success += 1

        total_done += 1
        app.state.zepto_cron_status["progress"] = total_done
        run_logger.update_progress(run_id, total_success, total_failed)

        # Collect update for batching
        batch_updates.append({
            "row": i + 2,
            "values": format_zepto_row(results_by_city),
        })

        # Flush batch if full or at end
        should_flush = (len(batch_updates) == BATCH_SIZE) or (i == len(pids) - 1)
        if should_flush:
            try:
                await sheets_client.async_batch_update_zepto_rows(sheet_id, new_tab, batch_updates)
                logger.info("Zepto: wrote batch of %d rows (%d/%d total)", 
                           len(batch_updates), total_done, len(pids))
                batch_updates = []
            except Exception:
                logger.exception("Zepto: failed to write batch at offset %d", i - len(batch_updates))
                batch_updates = []

        if i < len(pids) - 1:
            delay = random.uniform(
                float(os.getenv("ZEPTO_DELAY_MIN", "1.0")),
                float(os.getenv("ZEPTO_DELAY_MAX", "3.0")),
            )
            await asyncio.sleep(delay)

    elapsed = datetime.now(IST) - run_start
    minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
    logger.info("Zepto: run complete — %d PIDs × %d cities | tab '%s' | time: %dm %ds",
                len(pids), len(ZEPTO_LOCATIONS), new_tab, minutes, seconds)

    app.state.zepto_cron_status.update({
        "is_running": False,
        "last_run_duration_seconds": int(elapsed.total_seconds()),
        "last_run_processed": len(pids),
        "progress": len(pids),
    })

    run_logger.complete_log(run_id, total_success, total_failed, new_tab)


async def run_manual_flipkart_trigger(app) -> None:
    """Called when user manually triggers the Flipkart full scrape from the UI."""
    await _run_full_flipkart_scrape(app, tab_prefix="Flipkart_Manual", run_type="flipkart_manual")


async def run_manual_zepto_trigger(app) -> None:
    """Called when user manually triggers the Zepto full scrape from the UI."""
    await asyncio.sleep(0.1)
    await _run_full_zepto_scrape(app, tab_prefix="Zepto_Manual", run_type="zepto_manual")


async def _run_full_instamart_scrape(app, tab_prefix: str, run_type: str) -> None:
    """Core scrape logic for Instamart sheet-based runs.

    Reads PIDs from INSTAMART_SHEET_ID / INSTAMART_SOURCE_TAB, scrapes each PID
    across INSTAMART_CITIES, and writes a wide-format result tab.
    """
    sheets_client = app.state.sheets_client
    sheet_id = os.getenv("INSTAMART_SHEET_ID", "")
    source_tab = os.getenv("INSTAMART_SOURCE_TAB", "Sheet1")

    if not sheet_id:
        logger.error("Instamart: no sheet ID configured (set INSTAMART_SHEET_ID)")
        return

    run_start = datetime.now(IST)
    logger.info(
        "Instamart: starting %s scrape — sheet=%s source_tab=%s started_at=%s",
        run_type,
        sheet_id,
        source_tab,
        run_start.strftime("%H:%M:%S"),
    )

    try:
        source_rows = sheets_client.get_asins_with_rows(sheet_id, source_tab)
    except Exception:
        logger.exception("Instamart: failed to read PIDs from source tab")
        return

    if not source_rows:
        logger.warning("Instamart: no PIDs found in source tab '%s' — skipping", source_tab)
        return

    now = datetime.now(IST)
    new_tab = f"{tab_prefix}_{now.strftime('%Y-%m-%d_%H-%M')}"
    pids = [r["asin"] for r in source_rows]

    run_id = run_logger.create_log(run_type, len(pids))

    try:
        sheets_client.create_tab(sheet_id, new_tab)
        sheets_client.write_instamart_header_and_pids(sheet_id, new_tab, pids)
        logger.info("Instamart: created tab '%s' with %d PIDs", new_tab, len(pids))
    except Exception as e:
        logger.exception("Instamart: failed to create result tab '%s'", new_tab)
        app.state.instamart_cron_status.update({"is_running": False, "error": f"Failed to create tab '{new_tab}'"})
        run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
        return

    app.state.instamart_cron_status.update(
        {
            "is_running": True,
            "last_run_at": run_start.isoformat(),
            "last_run_tab": new_tab,
            "progress": 0,
            "total": len(pids),
            "last_run_duration_seconds": None,
            "last_run_processed": None,
            "error": None,
        }
    )

    # Import here to avoid circular imports / keep module load light.
    from instamart.scraper import fetch_instamart_data

    proxy_manager = app.state.proxy_manager

    total_done = 0
    total_success = 0
    total_failed = 0
    batch_updates = []
    BATCH_SIZE = 100  # Google Sheets API batch limit

    async def scrape_one_city(pid_: str, loc: dict) -> dict:
        async with batch_context(app.state):
            return await fetch_instamart_data(
                item_id=pid_,
                pincode=loc.get("pincode", ""),
                lat=loc["lat"],
                lon=loc["lng"],
                city=loc["name"],
                store_id=loc.get("store_id", ""),
                browser=get_browser(app.state),
                proxy_manager=proxy_manager,
            )

    for i, pid in enumerate(pids):
        # Scrape all cities for this PID concurrently.
        city_results = await asyncio.gather(
            *[scrape_one_city(pid, loc) for loc in INSTAMART_LOCATIONS],
            return_exceptions=True,
        )

        results_by_city: dict = {}
        for result in city_results:
            if isinstance(result, Exception):
                total_failed += 1
                continue
            city = result.get("city", "")
            if city:
                results_by_city[city] = result
            status = result.get("status", "error")
            if status == "error":
                total_failed += 1
            else:
                total_success += 1

        total_done += 1
        app.state.instamart_cron_status["progress"] = total_done
        run_logger.update_progress(run_id, total_success, total_failed)

        batch_updates.append({
            "row": i + 2,
            "values": format_instamart_row(results_by_city),
        })

        # Flush batch to Sheets
        should_flush = (len(batch_updates) == BATCH_SIZE) or (i == len(pids) - 1)
        if should_flush:
            try:
                await sheets_client.async_batch_update_instamart_rows(sheet_id, new_tab, batch_updates)
                logger.info(
                    "Instamart: wrote batch of %d rows (%d/%d total)",
                    len(batch_updates),
                    total_done,
                    len(pids),
                )
                batch_updates = []
            except Exception:
                logger.exception(
                    "Instamart: failed to write batch at offset %d",
                    i - len(batch_updates),
                )
                batch_updates = []

        if i < len(pids) - 1:
            delay = random.uniform(
                float(os.getenv("INSTAMART_DELAY_MIN", "1.0")),
                float(os.getenv("INSTAMART_DELAY_MAX", "3.0")),
            )
            await asyncio.sleep(delay)

    elapsed = datetime.now(IST) - run_start
    minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
    logger.info(
        "Instamart: run complete — %d PIDs × %d cities | tab '%s' | time: %dm %ds",
        len(pids),
        len(INSTAMART_LOCATIONS),
        new_tab,
        minutes,
        seconds,
    )

    app.state.instamart_cron_status.update({
        "is_running": False,
        "last_run_duration_seconds": int(elapsed.total_seconds()),
        "last_run_processed": len(pids),
        "progress": len(pids),
    })

    run_logger.complete_log(run_id, total_success, total_failed, new_tab)


async def run_manual_instamart_trigger(app) -> None:
    """Called when user manually triggers the Instamart full scrape from the UI."""
    await asyncio.sleep(0.1)
    await _run_full_instamart_scrape(app, tab_prefix="Instamart_Manual", run_type="instamart_manual")



async def _run_full_flipkart_scrape(app, tab_prefix: str, run_type: str) -> None:

    """Core scrape logic for Flipkart sheet-based runs.

    Reads FSNs from FLIPKART_SHEET_ID / FLIPKART_SOURCE_TAB, scrapes each FSN
    via Playwright, and writes results to a new tab in the Flipkart sheet.
    """
    sheets_client = app.state.sheets_client
    sheet_id = os.getenv("FLIPKART_SHEET_ID", "")
    source_tab = os.getenv("FLIPKART_SOURCE_TAB", "Sheet1")

    if not sheet_id:
        logger.error("Flipkart: no sheet ID configured (set FLIPKART_SHEET_ID)")
        return

    run_start = datetime.now(IST)
    logger.info("Flipkart: starting %s scrape — sheet=%s source_tab=%s started_at=%s",
                run_type, sheet_id, source_tab, run_start.strftime("%H:%M:%S"))

    try:
        source_rows = sheets_client.get_asins_with_rows(sheet_id, source_tab)
    except Exception:
        logger.exception("Flipkart: failed to read FSNs from source tab")
        return

    if not source_rows:
        logger.warning("Flipkart: no FSNs found in source tab '%s' — skipping run", source_tab)
        return

    now = datetime.now(IST)
    new_tab = f"{tab_prefix}_{now.strftime('%Y-%m-%d_%H-%M')}"
    fsns = [r["asin"] for r in source_rows]  # get_asins_with_rows uses "asin" key

    run_id = run_logger.create_log(run_type, len(fsns))

    try:
        sheets_client.create_tab(sheet_id, new_tab)
        sheets_client.write_header_and_fsns(sheet_id, new_tab, fsns)
        logger.info("Flipkart: created tab '%s' with %d FSNs", new_tab, len(fsns))
    except Exception as e:
        logger.exception("Flipkart: failed to create result tab '%s'", new_tab)
        app.state.flipkart_cron_status.update({"is_running": False, "error": f"Failed to create tab '{new_tab}'"})
        run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
        return

    # Remap row numbers — header is row 1, FSNs start at row 2
    remapped = [{"row": i + 2, "fsn": fsn} for i, fsn in enumerate(fsns)]

    app.state.flipkart_cron_status.update({
        "is_running": True,
        "last_run_at": run_start.isoformat(),
        "last_run_tab": new_tab,
        "progress": 0,
        "total": len(remapped),
        "last_run_duration_seconds": None,
        "last_run_processed": None,
        "error": None,
    })

    proxy_manager = app.state.proxy_manager

    async def scrape_one(row_data: dict) -> dict:
        async with batch_context(app.state):
            result = await scrape_flipkart(row_data["fsn"], get_browser(app.state), proxy_manager)
            result["row"] = row_data["row"]
            return result

    total_processed = 0
    total_success = 0
    total_failed = 0

    for chunk_start in range(0, len(remapped), CHUNK_SIZE):
        chunk = remapped[chunk_start : chunk_start + CHUNK_SIZE]
        try:
            chunk_results = await asyncio.gather(*[scrape_one(r) for r in chunk])
            updates = [_format_flipkart_update(res) for res in chunk_results]
            await sheets_client.async_batch_update_flipkart_rows(sheet_id, new_tab, updates)
            total_processed += len(chunk_results)

            for res in chunk_results:
                status = res.get("status", "error")
                if status in ("error", "not_found", "blocked", "invalid_format", "unavailable"):
                    total_failed += 1
                else:
                    total_success += 1

            app.state.flipkart_cron_status["progress"] = total_processed
            run_logger.update_progress(run_id, total_success, total_failed)
            logger.info("Flipkart: wrote chunk %d–%d to tab '%s' (%d/%d done)",
                        chunk[0]["row"], chunk[-1]["row"], new_tab, total_processed, len(remapped))
        except Exception:
            logger.exception("Flipkart: chunk write failed at offset %d — continuing", chunk_start)

    elapsed = datetime.now(IST) - run_start
    minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
    logger.info("Flipkart: run complete — %d/%d FSNs written to tab '%s' | total time: %dm %ds",
                total_processed, len(remapped), new_tab, minutes, seconds)

    app.state.flipkart_cron_status.update({
        "is_running": False,
        "last_run_duration_seconds": int(elapsed.total_seconds()),
        "last_run_processed": total_processed,
        "progress": total_processed,
    })

    run_logger.complete_log(run_id, total_success, total_failed, new_tab)


async def run_manual_flipkart_trigger(app) -> None:
    """Called when user manually triggers the Flipkart full scrape from the UI."""
    await _run_full_flipkart_scrape(app, tab_prefix="Flipkart_Manual", run_type="flipkart_manual")


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
