"""Cron scheduler — periodically scrapes all ASINs from the source tab and writes to a new result tab."""

import asyncio
import logging
import os

from datetime import datetime, timezone, timedelta
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils.scrape_helpers import (
    batch_context,
    CHUNK_SIZE,
    SCRAPE_CONCURRENCY,
    MANUAL_RESERVED,
    format_update as _format_update,
    format_flipkart_update as _format_flipkart_update,
    format_blinkit_row,
    format_zepto_row,
    format_instamart_row,
    format_flipkart_minutes_row,
    get_browser,
)

from amazon.scraper import scrape_amazon_with_retry, fetch_curl_supplement, merge_curl_supplement
from flipkart.scraper import scrape_flipkart
from blinkit.scraper import fetch_blinkit_data
from blinkit.locations import LOCATIONS as BLINKIT_LOCATIONS
from zepto.scraper import fetch_zepto_data
from zepto.locations import LOCATIONS as ZEPTO_LOCATIONS
from instamart.locations import LOCATIONS as INSTAMART_LOCATIONS
from flipkart_minutes.locations import LOCATIONS as FLIPKART_MINUTES_LOCATIONS
from utils import run_logger

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def _run_full_scrape(app, tab_prefix: str, run_type: str, write_historical: bool = True,
                           resume_tab: str | None = None) -> None:
    """Core scrape logic shared by both automatic cron and manual trigger.

    Args:
        app: FastAPI app instance (for browser, proxy_manager, cron_status)
        tab_prefix: Prefix for the new tab name (e.g. "Run" or "Manual_Trigger")
        run_type: "automatic" or "manual" — used for logging
        write_historical: If True, appends results to the Historical tab (cron only).
        resume_tab: Existing result tab to finish instead of creating a new one.
            Reads the tab's own ASIN column for the work list, so it is unaffected
            by edits to the source tab since the interrupted run started.
    """
    # Synchronous guard + lock. No await between check and set → no race in single-threaded asyncio.
    if app.state.cron_status.get("is_running"):
        logger.warning("Cron: %s run skipped — previous run still active", run_type)
        return
    app.state.cron_status["is_running"] = True

    try:
        sheets_client = app.state.sheets_client
        sheet_id = os.getenv("CRON_SHEET_ID") or os.getenv("SPREADSHEET_ID", "")
        source_tab = os.getenv("CRON_SOURCE_TAB") or os.getenv("WORKSHEET_NAME", "Sheet1")

        if not sheet_id:
            logger.error("Cron: no sheet ID configured (set CRON_SHEET_ID or SPREADSHEET_ID)")
            return

        run_start = datetime.now(IST)
        logger.info("Cron: starting %s scrape — sheet=%s source_tab=%s started_at=%s",
                    run_type, sheet_id, source_tab, run_start.strftime("%H:%M:%S"))

        resume_filled: list[list[str]] = []

        if resume_tab:
            new_tab = resume_tab
            try:
                remapped, resume_filled = sheets_client.get_pending_rows(sheet_id, new_tab)
            except Exception:
                logger.exception("Cron: failed to read resume tab '%s'", new_tab)
                return

            if not remapped:
                logger.info("Cron: resume tab '%s' already complete — nothing to do", new_tab)
                return

            run_id = run_logger.create_log(run_type, len(remapped), new_tab)
            logger.info("Cron: resuming tab '%s' — %d ASINs pending, %d already done",
                        new_tab, len(remapped), len(resume_filled))
        else:
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
            run_id = run_logger.create_log(run_type, len(asins), new_tab)

            try:
                sheets_client.create_tab(sheet_id, new_tab)
                sheets_client.write_header_and_asins(sheet_id, new_tab, asins)
                logger.info("Cron: created tab '%s' with %d ASINs", new_tab, len(asins))
            except Exception as e:
                logger.exception("Cron: failed to create result tab '%s'", new_tab)
                app.state.cron_status["error"] = f"Failed to create tab '{new_tab}'"
                run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
                return

            # Remap row numbers — header is row 1, ASINs start at row 2
            remapped = [{"row": i + 2, "asin": asin} for i, asin in enumerate(asins)]

        row_to_asin = {r["row"]: r["asin"] for r in remapped}
        # Seed with rows the interrupted run already wrote — Historical is only appended
        # at the end, so without this a resume would lose everything scraped before the crash.
        historical_rows: list[list] = [r + [new_tab] for r in resume_filled]

        app.state.cron_status.update({
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
                result = await scrape_amazon_with_retry(row_data["asin"], await get_browser(app.state), proxy_manager, skip_curl=True, browser_manager=app.state.browser_manager)
                result["row"] = row_data["row"]
            # semaphore released — curl runs here, overlapping with the next ASIN's Playwright scrape
            cookies = result.pop("_cookies", {}) or {}
            if cookies:
                curl_data = await fetch_curl_supplement(row_data["asin"], cookies)
                merge_curl_supplement(result, curl_data)
            return result

        total_processed = 0
        total_success = 0
        total_failed = 0

        # Bounded worker pool: at most (SCRAPE_CONCURRENCY - MANUAL_RESERVED) tasks live at once.
        # This prevents flooding the event loop with N waiting tasks, keeping manual requests responsive.
        n_workers = max(1, SCRAPE_CONCURRENCY - MANUAL_RESERVED)
        work_queue: asyncio.Queue = asyncio.Queue()
        for r in remapped:
            work_queue.put_nowait(r)
        results_queue: asyncio.Queue = asyncio.Queue()

        async def _worker():
            while True:
                try:
                    r = work_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    result = await scrape_one(r)
                except Exception:
                    logger.exception("Cron: scrape task raised unexpectedly")
                    result = {"status": "error", "row": r["row"]}
                await results_queue.put(result)

        worker_tasks: list[asyncio.Task] = []
        pending_writes: list[dict] = []

        try:
            worker_tasks = [asyncio.create_task(_worker()) for _ in range(n_workers)]

            for _ in range(len(remapped)):
                result = await results_queue.get()

                status = result.get("status", "error")
                if status in ("error", "not_found", "blocked", "invalid_format"):
                    total_failed += 1
                else:
                    total_success += 1
                total_processed += 1
                fmt = _format_update(result)
                pending_writes.append(fmt)
                asin = row_to_asin.get(result.get("row"), "")
                historical_rows.append([asin] + fmt["values"] + [new_tab])
                app.state.cron_status["progress"] = total_processed
                run_logger.update_progress(run_id, total_success, total_failed)

                if len(pending_writes) >= CHUNK_SIZE:
                    try:
                        await sheets_client.async_batch_update_rows(sheet_id, new_tab, pending_writes)
                        logger.info("Cron: wrote %d rows to '%s' (%d/%d done)",
                                    len(pending_writes), new_tab, total_processed, len(remapped))
                    except Exception:
                        logger.exception("Cron: rolling write failed — continuing")
                    pending_writes = []
        finally:
            for t in worker_tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            # Flush any buffered writes even if cancelled or exception escapes
            try:
                if pending_writes:
                    try:
                        await sheets_client.async_batch_update_rows(sheet_id, new_tab, pending_writes)
                        logger.info("Cron: wrote final %d rows to '%s'", len(pending_writes), new_tab)
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Cron: final write failed")
                hist_tab = os.getenv("AMAZON_HISTORICAL_TAB", "Historical")
                if write_historical and historical_rows:
                    try:
                        await sheets_client.async_append_to_historical(sheet_id, hist_tab, historical_rows)
                        logger.info("Cron: appended %d rows to '%s'", len(historical_rows), hist_tab)
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Cron: failed to append to historical tab '%s'", hist_tab)
                elif not write_historical:
                    logger.info("Cron: skipping historical append (manual trigger)")
            finally:
                run_logger.complete_log(run_id, total_success, total_failed, new_tab)

        elapsed = datetime.now(IST) - run_start
        minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
        logger.info("Cron: run complete — %d/%d ASINs written to tab '%s' | total time: %dm %ds",
                    total_processed, len(remapped), new_tab, minutes, seconds)

        app.state.cron_status.update({
            "last_run_duration_seconds": int(elapsed.total_seconds()),
            "last_run_processed": total_processed,
            "progress": total_processed,
        })

    finally:
        app.state.cron_status["is_running"] = False


async def run_scheduled_scrape(app) -> None:
    """Called by APScheduler on cron intervals."""
    if app.state.cron_status.get("is_running"):
        logger.warning("Cron: scheduled scrape skipped — a run is already active (duplicate trigger?)")
        return
    await _run_full_scrape(app, tab_prefix="Run", run_type="automatic")


async def resume_interrupted_scrape(app) -> None:
    """On startup, finish an automatic Amazon run that a crash or host reboot cut short.

    Called from the lifespan startup. The interrupted entry is failed first, so the
    resume's own log entry becomes the next resume target if this run dies too.
    """
    try:
        stale = next(
            (e for e in run_logger.get_all_logs()
             if e.get("status") == "in_progress"
             and e.get("type") == "automatic"
             and e.get("sheet_tab")),
            None,
        )
    except Exception:
        logger.exception("Cron: could not read run log for resume check")
        return

    if not stale:
        return

    logger.warning("Cron: run %s left in_progress on tab '%s' — resuming",
                   stale["run_id"], stale["sheet_tab"])
    run_logger.fail_log(stale["run_id"], "Interrupted (crash or reboot) — resumed in a new run")
    await _run_full_scrape(app, tab_prefix="Run", run_type="automatic",
                           resume_tab=stale["sheet_tab"])


async def run_manual_trigger(app) -> None:
    """Called when user manually triggers the full scrape from the UI."""
    await asyncio.sleep(0.1)
    await _run_full_scrape(app, tab_prefix="Manual_Trigger", run_type="manual", write_historical=False)


async def _run_full_blinkit_scrape(app, tab_prefix: str, run_type: str, write_historical: bool = False) -> None:
    """Core scrape logic for Blinkit sheet-based runs.

    Reads PIDs from BLINKIT_SHEET_ID / BLINKIT_SOURCE_TAB, scrapes all 10 cities
    per PID, and writes a wide-format result tab.
    """
    # Synchronous guard + lock. No await between check and set → no race in single-threaded asyncio.
    if app.state.blinkit_cron_status.get("is_running"):
        logger.warning("Blinkit: %s run skipped — previous run still active", run_type)
        return
    app.state.blinkit_cron_status["is_running"] = True

    try:
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
            app.state.blinkit_cron_status["error"] = f"Failed to create tab '{new_tab}'"
            run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
            return

        app.state.blinkit_cron_status.update({
            "last_run_at": run_start.isoformat(),
            "last_run_tab": new_tab,
            "progress": 0,
            "total": len(pids),
            "last_run_duration_seconds": None,
            "last_run_processed": None,
            "error": None,
        })

        proxy_manager = app.state.proxy_manager
        sem = asyncio.Semaphore(int(os.getenv("BLINKIT_CONCURRENCY", "10")))
        loop = asyncio.get_running_loop()

        async def scrape_one_city(pid: str, loc: dict) -> tuple[str, dict]:
            async with sem:
                try:
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
                except Exception:
                    result = {"city": loc["name"], "status": "error"}
            return (pid, result)

        async def scrape_pid(pid: str) -> tuple[str, dict]:
            """Scrape all cities for one PID, returning aggregated city results."""
            city_results: dict[str, dict] = {}
            if not BLINKIT_LOCATIONS:
                return (pid, city_results)
                
            first_loc = BLINKIT_LOCATIONS[0]
            _, result1 = await scrape_one_city(pid, first_loc)
            city_results[first_loc["name"]] = result1
            
            city_tasks = [asyncio.create_task(scrape_one_city(pid, loc)) for loc in BLINKIT_LOCATIONS[1:]]
            try:
                for coro in asyncio.as_completed(city_tasks):
                    try:
                        _, result = await coro
                    except Exception:
                        logger.exception("Blinkit: city task error for pid=%s", pid)
                        continue
                    city = result.get("city", "")
                    if city:
                        city_results[city] = result
                    else:
                        logger.warning("Blinkit: result missing city field for pid=%s", pid)
            finally:
                for t in city_tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*city_tasks, return_exceptions=True)
            return (pid, city_results)

        total_done = 0
        total_success = 0
        total_failed = 0
        batch_updates = []
        historical_rows: list[list] = []
        BATCH_SIZE = 100

        pid_index: dict[str, int] = {pid: i for i, pid in enumerate(pids)}

        # Bounded PID workers: each worker handles one PID (10 city sub-tasks) at a time.
        # Max in-flight tasks = n_pid_workers × 10, instead of len(pids) × 10.
        n_pid_workers = min(len(pids), max(1, int(os.getenv("BLINKIT_CONCURRENCY", "10")) // 2))
        work_queue: asyncio.Queue = asyncio.Queue()
        for pid in pids:
            work_queue.put_nowait(pid)
        results_queue: asyncio.Queue = asyncio.Queue()

        async def _pid_worker():
            while True:
                try:
                    pid = work_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    result = await scrape_pid(pid)
                except Exception:
                    logger.exception("Blinkit: pid worker error for pid=%s", pid)
                    result = (pid, {})
                await results_queue.put(result)

        pid_worker_tasks: list[asyncio.Task] = []

        try:
            pid_worker_tasks = [asyncio.create_task(_pid_worker()) for _ in range(n_pid_workers)]

            for _ in range(len(pids)):
                pid, city_results = await results_queue.get()

                for r in city_results.values():
                    if r.get("status", "error") == "error":
                        total_failed += 1
                    else:
                        total_success += 1

                i = pid_index[pid]
                total_done += 1
                app.state.blinkit_cron_status["progress"] = total_done
                run_logger.update_progress(run_id, total_success, total_failed)

                row_values = format_blinkit_row(city_results)
                batch_updates.append({
                    "row": i + 2,
                    "values": row_values,
                })
                historical_rows.append([pid] + row_values + [new_tab])

                should_flush = (len(batch_updates) == BATCH_SIZE) or (total_done == len(pids))
                if should_flush:
                    try:
                        await sheets_client.async_batch_update_blinkit_rows(sheet_id, new_tab, batch_updates)
                        logger.info("Blinkit: wrote batch of %d rows (%d/%d total)",
                                   len(batch_updates), total_done, len(pids))
                        batch_updates = []
                    except Exception:
                        logger.exception("Blinkit: failed to write batch")
                        batch_updates = []
        finally:
            for t in pid_worker_tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*pid_worker_tasks, return_exceptions=True)
            try:
                if batch_updates:
                    try:
                        await sheets_client.async_batch_update_blinkit_rows(sheet_id, new_tab, batch_updates)
                        logger.info("Blinkit: flushed final %d rows on shutdown", len(batch_updates))
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Blinkit: final flush failed on shutdown")
                hist_tab = os.getenv("BLINKIT_HISTORICAL_TAB", "HISTORY")
                if write_historical and historical_rows:
                    try:
                        loop = asyncio.get_running_loop()
                        existing = await loop.run_in_executor(None, sheets_client.list_tabs, sheet_id)
                        if hist_tab not in existing:
                            await loop.run_in_executor(None, sheets_client.create_tab, sheet_id, hist_tab)
                        await sheets_client.async_append_to_historical(sheet_id, hist_tab, historical_rows)
                        logger.info("Blinkit: appended %d rows to '%s'", len(historical_rows), hist_tab)
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Blinkit: failed to append to historical tab '%s'", hist_tab)
                elif not write_historical:
                    logger.info("Blinkit: skipping historical append (manual trigger)")
            finally:
                run_logger.complete_log(run_id, total_success, total_failed, new_tab)

        logger.info("Blinkit: all %d PIDs processed — tab '%s'", len(pids), new_tab)

        elapsed = datetime.now(IST) - run_start
        minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
        logger.info("Blinkit: run complete — %d PIDs × %d cities | tab '%s' | time: %dm %ds",
                    len(pids), len(BLINKIT_LOCATIONS), new_tab, minutes, seconds)

        app.state.blinkit_cron_status.update({
            "last_run_duration_seconds": int(elapsed.total_seconds()),
            "last_run_processed": len(pids),
            "progress": len(pids),
        })

    finally:
        app.state.blinkit_cron_status["is_running"] = False


async def run_scheduled_blinkit_scrape(app) -> None:
    """Called by APScheduler on cron intervals."""
    if app.state.blinkit_cron_status.get("is_running"):
        logger.warning("Blinkit: scheduled scrape skipped — a run is already active (duplicate trigger?)")
        return
    await _run_full_blinkit_scrape(app, tab_prefix="Blinkit_Run", run_type="blinkit_automatic", write_historical=True)


async def run_manual_blinkit_trigger(app) -> None:
    """Called when user manually triggers the Blinkit full scrape from the UI."""
    await asyncio.sleep(0.1)
    await _run_full_blinkit_scrape(app, tab_prefix="Blinkit_Manual", run_type="blinkit_manual")


async def _run_full_zepto_scrape(app, tab_prefix: str, run_type: str, write_historical: bool = False) -> None:
    """Core scrape logic for Zepto sheet-based runs."""
    # Synchronous guard + lock. No await between check and set → no race in single-threaded asyncio.
    if app.state.zepto_cron_status.get("is_running"):
        logger.warning("Zepto: %s run skipped — previous run still active", run_type)
        return
    app.state.zepto_cron_status["is_running"] = True

    try:
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
            app.state.zepto_cron_status["error"] = f"Failed to create tab '{new_tab}'"
            run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
            return

        app.state.zepto_cron_status.update({
            "last_run_at": run_start.isoformat(),
            "last_run_tab": new_tab,
            "progress": 0,
            "total": len(pids),
            "last_run_duration_seconds": None,
            "last_run_processed": None,
            "error": None,
        })

        proxy_manager = app.state.zepto_proxy_manager
        loop = asyncio.get_running_loop()

        async def scrape_one_city(pid: str, loc: dict, fallback_title: str | None = None, fallback_mrp: float | None = None) -> tuple[str, dict]:
            async with batch_context(app.state):
                try:
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
                            fallback_title=fallback_title,
                            fallback_mrp=fallback_mrp,
                        ),
                    )
                except Exception:
                    result = {"city": loc["name"], "status": "error"}
            return (pid, result)

        async def scrape_pid(pid: str) -> tuple[str, dict]:
            """Scrape all cities for one PID, returning aggregated city results."""
            city_results: dict[str, dict] = {}
            if not ZEPTO_LOCATIONS:
                return (pid, city_results)
                
            first_loc = ZEPTO_LOCATIONS[0]
            _, result1 = await scrape_one_city(pid, first_loc)
            city_results[first_loc["name"]] = result1
            
            fallback_title = result1.get("title")
            fallback_mrp = result1.get("mrp")
            if fallback_title in ("Not Found", "Unknown Product"):
                fallback_title = None
                 
            city_tasks = [asyncio.create_task(scrape_one_city(pid, loc, fallback_title, fallback_mrp)) for loc in ZEPTO_LOCATIONS[1:]]
            try:
                for coro in asyncio.as_completed(city_tasks):
                    try:
                        _, result = await coro
                    except Exception:
                        logger.exception("Zepto: city task error for pid=%s", pid)
                        continue
                    city = result.get("city", "")
                    if city:
                        city_results[city] = result
                    else:
                        logger.warning("Zepto: result missing city field for pid=%s", pid)
            finally:
                for t in city_tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*city_tasks, return_exceptions=True)
            return (pid, city_results)

        total_done = 0
        total_success = 0
        total_failed = 0
        batch_updates = []
        historical_rows: list[list] = []
        BATCH_SIZE = 100

        pid_index: dict[str, int] = {pid: i for i, pid in enumerate(pids)}

        # Bounded PID workers: max in-flight tasks = n_pid_workers × 9, not len(pids) × 9.
        n_pid_workers = min(len(pids), max(1, SCRAPE_CONCURRENCY))
        work_queue: asyncio.Queue = asyncio.Queue()
        for pid in pids:
            work_queue.put_nowait(pid)
        results_queue: asyncio.Queue = asyncio.Queue()

        async def _pid_worker():
            while True:
                try:
                    pid = work_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    result = await scrape_pid(pid)
                except Exception:
                    logger.exception("Zepto: pid worker error for pid=%s", pid)
                    result = (pid, {})
                await results_queue.put(result)

        pid_worker_tasks: list[asyncio.Task] = []

        try:
            pid_worker_tasks = [asyncio.create_task(_pid_worker()) for _ in range(n_pid_workers)]

            for _ in range(len(pids)):
                pid, city_results = await results_queue.get()

                for r in city_results.values():
                    if r.get("status", "error") == "error":
                        total_failed += 1
                    else:
                        total_success += 1

                i = pid_index[pid]
                total_done += 1
                app.state.zepto_cron_status["progress"] = total_done
                run_logger.update_progress(run_id, total_success, total_failed)

                row_values = format_zepto_row(city_results)
                batch_updates.append({
                    "row": i + 2,
                    "values": row_values,
                })
                historical_rows.append([pid] + row_values + [new_tab])

                should_flush = (len(batch_updates) == BATCH_SIZE) or (total_done == len(pids))
                if should_flush:
                    try:
                        await sheets_client.async_batch_update_zepto_rows(sheet_id, new_tab, batch_updates)
                        logger.info("Zepto: wrote batch of %d rows (%d/%d total)",
                                   len(batch_updates), total_done, len(pids))
                        batch_updates = []
                    except Exception:
                        logger.exception("Zepto: failed to write batch")
                        batch_updates = []
        finally:
            for t in pid_worker_tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*pid_worker_tasks, return_exceptions=True)
            try:
                if batch_updates:
                    try:
                        await sheets_client.async_batch_update_zepto_rows(sheet_id, new_tab, batch_updates)
                        logger.info("Zepto: flushed final %d rows on shutdown", len(batch_updates))
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Zepto: final flush failed on shutdown")
                hist_tab = os.getenv("ZEPTO_HISTORICAL_TAB", "HISTORY")
                if write_historical and historical_rows:
                    try:
                        loop = asyncio.get_running_loop()
                        existing = await loop.run_in_executor(None, sheets_client.list_tabs, sheet_id)
                        if hist_tab not in existing:
                            await loop.run_in_executor(None, sheets_client.create_tab, sheet_id, hist_tab)
                        await sheets_client.async_append_to_historical(sheet_id, hist_tab, historical_rows)
                        logger.info("Zepto: appended %d rows to '%s'", len(historical_rows), hist_tab)
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Zepto: failed to append to historical tab '%s'", hist_tab)
                elif not write_historical:
                    logger.info("Zepto: skipping historical append (manual trigger)")
            finally:
                run_logger.complete_log(run_id, total_success, total_failed, new_tab)

        elapsed = datetime.now(IST) - run_start
        minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
        logger.info("Zepto: run complete — %d PIDs × %d cities | tab '%s' | time: %dm %ds",
                    len(pids), len(ZEPTO_LOCATIONS), new_tab, minutes, seconds)

        app.state.zepto_cron_status.update({
            "last_run_duration_seconds": int(elapsed.total_seconds()),
            "last_run_processed": len(pids),
            "progress": len(pids),
        })

    finally:
        app.state.zepto_cron_status["is_running"] = False


async def run_scheduled_zepto_scrape(app) -> None:
    """Called by APScheduler on cron intervals."""
    if app.state.zepto_cron_status.get("is_running"):
        logger.warning("Zepto: scheduled scrape skipped — a run is already active (duplicate trigger?)")
        return
    await _run_full_zepto_scrape(app, tab_prefix="Zepto_Run", run_type="zepto_automatic", write_historical=True)


async def run_manual_zepto_trigger(app) -> None:
    """Called when user manually triggers the Zepto full scrape from the UI."""
    await asyncio.sleep(0.1)
    await _run_full_zepto_scrape(app, tab_prefix="Zepto_Manual", run_type="zepto_manual")


async def _run_full_instamart_scrape(app, tab_prefix: str, run_type: str, write_historical: bool = False) -> None:
    """Core scrape logic for Instamart sheet-based runs.

    Reads PIDs from INSTAMART_SHEET_ID / INSTAMART_SOURCE_TAB, scrapes each PID
    across INSTAMART_CITIES, and writes a wide-format result tab.
    """
    # Synchronous guard + lock. No await between check and set → no race in single-threaded asyncio.
    if app.state.instamart_cron_status.get("is_running"):
        logger.warning("Instamart: %s run skipped — previous run still active", run_type)
        return
    app.state.instamart_cron_status["is_running"] = True

    try:
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
            app.state.instamart_cron_status["error"] = f"Failed to create tab '{new_tab}'"
            run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
            return

        app.state.instamart_cron_status.update({
            "last_run_at": run_start.isoformat(),
            "last_run_tab": new_tab,
            "progress": 0,
            "total": len(pids),
            "last_run_duration_seconds": None,
            "last_run_processed": None,
            "error": None,
        })

        # Swiggy Instamart is now a WAF-gated, client-rendered SPA (no SSR price).
        # We scrape it with a real browser, city-major: one reused context per city
        # (location set via GPS spoof), sweeping all PIDs, then closed. See
        # instamart/browser_scraper.py for why curl/SSR parsing no longer works.
        from instamart.browser_scraper import sweep_city

        browser_manager = getattr(app.state, "browser_manager", None)
        if browser_manager is None or not getattr(browser_manager, "browsers", None):
            logger.error("Instamart: no Playwright browser pool — cannot scrape")
            app.state.instamart_cron_status["error"] = "browser pool unavailable"
            run_logger.fail_log(run_id, "browser pool unavailable")
            return

        total_done = 0
        total_success = 0
        total_failed = 0
        batch_updates = []
        historical_rows: list[list] = []
        BATCH_SIZE = 100  # Google Sheets API batch limit

        pid_index: dict[str, int] = {pid: i for i, pid in enumerate(pids)}
        n_cities = max(1, len(INSTAMART_LOCATIONS))
        # matrix[pid][city] accumulates results; rows are written pid-major at the end.
        matrix: dict[str, dict[str, dict]] = {pid: {} for pid in pids}

        # Bound concurrent city contexts to keep RAM sane on small VPS (each context
        # is a heavy Chromium SPA render). Default 3; tune via env.
        city_conc = max(1, min(n_cities, int(os.getenv("INSTAMART_CITY_CONCURRENCY", "3"))))
        city_sem = asyncio.Semaphore(city_conc)
        cells_total = len(pids) * n_cities
        progress = {"cells": 0}
        proxy_pool = getattr(app.state, "instamart_proxy_pool", None)

        def _on_cell(pid: str, r: dict) -> None:
            progress["cells"] += 1
            # Map cell progress onto the PID scale the UI expects.
            app.state.instamart_cron_status["progress"] = progress["cells"] // n_cities

        async def _sweep(loc: dict) -> None:
            try:
                browser = await browser_manager.acquire()
            except RuntimeError:
                logger.error("Instamart: no browser available for city %s", loc["name"])
                return
            async with city_sem:
                try:
                    city_results = await sweep_city(browser, loc, pids, on_result=_on_cell,
                                                    proxy_pool=proxy_pool)
                except Exception:
                    logger.exception("Instamart: city sweep failed for %s", loc["name"])
                    city_results = {}
            for pid, r in city_results.items():
                matrix.setdefault(pid, {})[loc["name"]] = r

        logger.info("Instamart: sweeping %d cities × %d PIDs (%d contexts at a time)",
                    n_cities, len(pids), city_conc)
        await asyncio.gather(*[asyncio.create_task(_sweep(loc)) for loc in INSTAMART_LOCATIONS])

        # Build rows pid-major from the matrix and flush in batches.
        for pid in pids:
            city_results = matrix.get(pid, {})
            for r in city_results.values():
                if r.get("status", "error") == "error":
                    total_failed += 1
                else:
                    total_success += 1

            i = pid_index[pid]
            total_done += 1
            app.state.instamart_cron_status["progress"] = total_done
            run_logger.update_progress(run_id, total_success, total_failed)

            row_values = format_instamart_row(city_results)
            batch_updates.append({"row": i + 2, "values": row_values})
            historical_rows.append([pid] + row_values + [new_tab])

            should_flush = (len(batch_updates) == BATCH_SIZE) or (total_done == len(pids))
            if should_flush:
                try:
                    await sheets_client.async_batch_update_instamart_rows(sheet_id, new_tab, batch_updates)
                    logger.info(
                        "Instamart: wrote batch of %d rows (%d/%d total)",
                        len(batch_updates), total_done, len(pids),
                    )
                    batch_updates = []
                except Exception:
                    logger.exception("Instamart: failed to write batch")
                    batch_updates = []
            try:
                if batch_updates:
                    try:
                        await sheets_client.async_batch_update_instamart_rows(sheet_id, new_tab, batch_updates)
                        logger.info("Instamart: flushed final %d rows on shutdown", len(batch_updates))
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Instamart: final flush failed on shutdown")
                hist_tab = os.getenv("INSTAMART_HISTORICAL_TAB", "HISTORY")
                if write_historical and historical_rows:
                    try:
                        loop = asyncio.get_running_loop()
                        existing = await loop.run_in_executor(None, sheets_client.list_tabs, sheet_id)
                        if hist_tab not in existing:
                            await loop.run_in_executor(None, sheets_client.create_tab, sheet_id, hist_tab)
                        await sheets_client.async_append_to_historical(sheet_id, hist_tab, historical_rows)
                        logger.info("Instamart: appended %d rows to '%s'", len(historical_rows), hist_tab)
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Instamart: failed to append to historical tab '%s'", hist_tab)
                elif not write_historical:
                    logger.info("Instamart: skipping historical append (manual trigger)")
            finally:
                run_logger.complete_log(run_id, total_success, total_failed, new_tab)

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
            "last_run_duration_seconds": int(elapsed.total_seconds()),
            "last_run_processed": len(pids),
            "progress": len(pids),
        })

    finally:
        app.state.instamart_cron_status["is_running"] = False


async def run_scheduled_instamart_scrape(app) -> None:
    """Called by APScheduler on cron intervals."""
    if app.state.instamart_cron_status.get("is_running"):
        logger.warning("Instamart: scheduled scrape skipped — a run is already active (duplicate trigger?)")
        return
    await _run_full_instamart_scrape(app, tab_prefix="Instamart_Run", run_type="instamart_automatic", write_historical=True)


async def run_manual_instamart_trigger(app) -> None:
    """Called when user manually triggers the Instamart full scrape from the UI."""
    await asyncio.sleep(0.1)
    await _run_full_instamart_scrape(app, tab_prefix="Instamart_Manual", run_type="instamart_manual")


async def _run_full_flipkart_minutes_scrape(app, tab_prefix: str, run_type: str) -> None:
    """Core scrape logic for Flipkart Minutes sheet-based runs.

    Reads PIDs from FLIPKART_MINUTES_SHEET_ID / FLIPKART_MINUTES_SOURCE_TAB, scrapes each PID
    across FLIPKART_MINUTES_CITIES, and writes a wide-format result tab.
    """
    if app.state.flipkart_minutes_cron_status.get("is_running"):
        logger.warning("Flipkart Minutes: %s run skipped — previous run still active", run_type)
        return
    app.state.flipkart_minutes_cron_status["is_running"] = True

    try:
        sheets_client = app.state.sheets_client
        sheet_id = os.getenv("FLIPKART_MINUTES_SHEET_ID", "")
        source_tab = os.getenv("FLIPKART_MINUTES_SOURCE_TAB", "Sheet1")

        if not sheet_id:
            logger.error("Flipkart Minutes: no sheet ID configured (set FLIPKART_MINUTES_SHEET_ID)")
            return

        run_start = datetime.now(IST)
        logger.info(
            "Flipkart Minutes: starting %s scrape — sheet=%s source_tab=%s started_at=%s",
            run_type,
            sheet_id,
            source_tab,
            run_start.strftime("%H:%M:%S"),
        )

        try:
            source_rows = sheets_client.get_asins_with_rows(sheet_id, source_tab)
        except Exception:
            logger.exception("Flipkart Minutes: failed to read PIDs from source tab")
            return

        if not source_rows:
            logger.warning("Flipkart Minutes: no PIDs found in source tab '%s' — skipping", source_tab)
            return

        now = datetime.now(IST)
        new_tab = f"{tab_prefix}_{now.strftime('%Y-%m-%d_%H-%M')}"
        pids = [r["asin"] for r in source_rows]

        run_id = run_logger.create_log(run_type, len(pids))

        try:
            sheets_client.create_tab(sheet_id, new_tab)
            try:
                sheets_client.write_flipkart_minutes_header_and_pids(sheet_id, new_tab, pids)
            except AttributeError:
                pass # It's a base implementation, we'll need to update GoogleSheetsClient later
            logger.info("Flipkart Minutes: created tab '%s' with %d PIDs", new_tab, len(pids))
        except Exception as e:
            logger.exception("Flipkart Minutes: failed to create result tab '%s'", new_tab)
            app.state.flipkart_minutes_cron_status["error"] = f"Failed to create tab '{new_tab}'"
            run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
            return

        app.state.flipkart_minutes_cron_status.update({
            "last_run_at": run_start.isoformat(),
            "last_run_tab": new_tab,
            "progress": 0,
            "total": len(pids),
            "last_run_duration_seconds": None,
            "last_run_processed": None,
            "error": None,
        })

        from flipkart_minutes.scraper import fetch_flipkart_minutes_data

        total_done = 0
        total_success = 0
        total_failed = 0
        batch_updates = []
        BATCH_SIZE = 100

        async def scrape_one_city(pid_: str, loc: dict) -> tuple[str, dict]:
            async with batch_context(app.state):
                try:
                    result = await fetch_flipkart_minutes_data(
                        pid=pid_,
                        city=loc["name"],
                        app_state=app.state,
                    )
                except Exception:
                    result = {"city": loc["name"], "status": "error"}
            return (pid_, result)

        async def scrape_pid(pid: str) -> tuple[str, dict]:
            city_results: dict[str, dict] = {}
            if not FLIPKART_MINUTES_LOCATIONS:
                return (pid, city_results)
                
            first_loc = FLIPKART_MINUTES_LOCATIONS[0]
            _, result1 = await scrape_one_city(pid, first_loc)
            city_results[first_loc["name"]] = result1
            
            city_tasks = [asyncio.create_task(scrape_one_city(pid, loc)) for loc in FLIPKART_MINUTES_LOCATIONS[1:]]
            try:
                for coro in asyncio.as_completed(city_tasks):
                    try:
                        _, result = await coro
                    except Exception:
                        logger.exception("Flipkart Minutes: city task error for pid=%s", pid)
                        continue
                    city = result.get("city", "")
                    if city:
                        city_results[city] = result
                    else:
                        logger.warning("Flipkart Minutes: result missing city field for pid=%s", pid)
            finally:
                for t in city_tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*city_tasks, return_exceptions=True)
            return (pid, city_results)

        pid_index: dict[str, int] = {pid: i for i, pid in enumerate(pids)}
        n_pid_workers = min(len(pids), max(1, SCRAPE_CONCURRENCY - MANUAL_RESERVED))
        work_queue: asyncio.Queue = asyncio.Queue()
        for pid in pids:
            work_queue.put_nowait(pid)
        results_queue: asyncio.Queue = asyncio.Queue()

        async def _pid_worker():
            while True:
                try:
                    pid = work_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    result = await scrape_pid(pid)
                except Exception:
                    logger.exception("Flipkart Minutes: pid worker error for pid=%s", pid)
                    result = (pid, {})
                await results_queue.put(result)

        pid_worker_tasks: list[asyncio.Task] = []

        try:
            pid_worker_tasks = [asyncio.create_task(_pid_worker()) for _ in range(n_pid_workers)]

            for _ in range(len(pids)):
                pid, city_results = await results_queue.get()

                for r in city_results.values():
                    if r.get("status", "error") == "error":
                        total_failed += 1
                    else:
                        total_success += 1

                i = pid_index[pid]
                total_done += 1
                app.state.flipkart_minutes_cron_status["progress"] = total_done
                run_logger.update_progress(run_id, total_success, total_failed)

                batch_updates.append({
                    "row": i + 2,
                    "values": format_flipkart_minutes_row(city_results),
                })

                should_flush = (len(batch_updates) == BATCH_SIZE) or (total_done == len(pids))
                if should_flush:
                    try:
                        try:
                            await sheets_client.async_batch_update_flipkart_minutes_rows(sheet_id, new_tab, batch_updates)
                        except AttributeError:
                            pass
                        logger.info(
                            "Flipkart Minutes: wrote batch of %d rows (%d/%d total)",
                            len(batch_updates), total_done, len(pids),
                        )
                        batch_updates = []
                    except Exception:
                        logger.exception("Flipkart Minutes: failed to write batch")
                        batch_updates = []
        finally:
            for t in pid_worker_tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*pid_worker_tasks, return_exceptions=True)
            try:
                if batch_updates:
                    try:
                        try:
                            await sheets_client.async_batch_update_flipkart_minutes_rows(sheet_id, new_tab, batch_updates)
                        except AttributeError:
                            pass
                        logger.info("Flipkart Minutes: flushed final %d rows on shutdown", len(batch_updates))
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Flipkart Minutes: final flush failed on shutdown")
            finally:
                run_logger.complete_log(run_id, total_success, total_failed, new_tab)

        elapsed = datetime.now(IST) - run_start
        minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
        logger.info(
            "Flipkart Minutes: run complete — %d PIDs × %d cities | tab '%s' | time: %dm %ds",
            len(pids),
            len(FLIPKART_MINUTES_LOCATIONS),
            new_tab,
            minutes,
            seconds,
        )

        app.state.flipkart_minutes_cron_status.update({
            "last_run_duration_seconds": int(elapsed.total_seconds()),
            "last_run_processed": len(pids),
            "progress": len(pids),
        })

    finally:
        app.state.flipkart_minutes_cron_status["is_running"] = False


async def run_manual_flipkart_minutes_trigger(app) -> None:
    """Called when user manually triggers the Flipkart Minutes full scrape from the UI."""
    await asyncio.sleep(0.1)
    await _run_full_flipkart_minutes_scrape(app, tab_prefix="Flipkart_Minutes_Manual", run_type="flipkart_minutes_manual")



async def _run_full_flipkart_scrape(app, tab_prefix: str, run_type: str, write_historical: bool = True) -> None:
    """Core scrape logic for Flipkart sheet-based runs.

    Reads FSNs from FLIPKART_SHEET_ID / FLIPKART_SOURCE_TAB, scrapes each FSN
    via Playwright, and writes results to a new tab in the Flipkart sheet.

    Args:
        write_historical: If True, appends results to the Historical tab (cron only).
    """
    # Synchronous guard + lock. No await between check and set → no race in single-threaded asyncio.
    if app.state.flipkart_cron_status.get("is_running"):
        logger.warning("Flipkart: %s run skipped — previous run still active", run_type)
        return
    app.state.flipkart_cron_status["is_running"] = True

    try:
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
            app.state.flipkart_cron_status["error"] = f"Failed to create tab '{new_tab}'"
            run_logger.fail_log(run_id, f"Failed to create tab '{new_tab}': {e}")
            return

        # Remap row numbers — header is row 1, FSNs start at row 2
        remapped = [{"row": i + 2, "fsn": fsn} for i, fsn in enumerate(fsns)]
        row_to_fsn = {r["row"]: r["fsn"] for r in remapped}
        historical_rows: list[list] = []

        app.state.flipkart_cron_status.update({
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
                result = await scrape_flipkart(row_data["fsn"], await get_browser(app.state), proxy_manager)
                result["row"] = row_data["row"]
                return result

        total_processed = 0
        total_success = 0
        total_failed = 0

        # Bounded worker pool: at most (SCRAPE_CONCURRENCY - MANUAL_RESERVED) tasks live at once.
        n_workers = max(1, SCRAPE_CONCURRENCY - MANUAL_RESERVED)
        work_queue: asyncio.Queue = asyncio.Queue()
        for r in remapped:
            work_queue.put_nowait(r)
        results_queue: asyncio.Queue = asyncio.Queue()

        async def _worker():
            while True:
                try:
                    r = work_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    result = await scrape_one(r)
                except Exception:
                    logger.exception("Flipkart cron: scrape task raised unexpectedly")
                    result = {"status": "error", "row": r["row"], "fsn": r["fsn"]}
                await results_queue.put(result)

        worker_tasks: list[asyncio.Task] = []
        pending_writes: list[dict] = []

        try:
            worker_tasks = [asyncio.create_task(_worker()) for _ in range(n_workers)]

            for _ in range(len(remapped)):
                result = await results_queue.get()

                status = result.get("status", "error")
                if status in ("error", "not_found", "blocked", "invalid_format", "unavailable"):
                    total_failed += 1
                else:
                    total_success += 1
                total_processed += 1
                fmt = _format_flipkart_update(result)
                pending_writes.append(fmt)
                fsn = result.get("fsn") or row_to_fsn.get(result.get("row"), "")
                historical_rows.append([fsn] + fmt["values"] + [new_tab])
                app.state.flipkart_cron_status["progress"] = total_processed
                run_logger.update_progress(run_id, total_success, total_failed)

                if len(pending_writes) >= CHUNK_SIZE:
                    try:
                        await sheets_client.async_batch_update_flipkart_rows(sheet_id, new_tab, pending_writes)
                        logger.info("Flipkart cron: wrote %d rows to '%s' (%d/%d done)",
                                    len(pending_writes), new_tab, total_processed, len(remapped))
                    except Exception:
                        logger.exception("Flipkart cron: rolling write failed — continuing")
                    pending_writes = []
        finally:
            for t in worker_tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            try:
                if pending_writes:
                    try:
                        await sheets_client.async_batch_update_flipkart_rows(sheet_id, new_tab, pending_writes)
                        logger.info("Flipkart cron: wrote final %d rows to '%s'", len(pending_writes), new_tab)
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Flipkart cron: final write failed")
                hist_tab = os.getenv("FLIPKART_HISTORICAL_TAB", "HISTORICAL")
                if write_historical and historical_rows:
                    try:
                        await sheets_client.async_append_to_historical(sheet_id, hist_tab, historical_rows)
                        logger.info("Flipkart cron: appended %d rows to '%s'", len(historical_rows), hist_tab)
                    except (Exception, asyncio.CancelledError):
                        logger.exception("Flipkart cron: failed to append to historical tab '%s'", hist_tab)
                elif not write_historical:
                    logger.info("Flipkart cron: skipping historical append (manual trigger)")
            finally:
                run_logger.complete_log(run_id, total_success, total_failed, new_tab)

        elapsed = datetime.now(IST) - run_start
        minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
        logger.info("Flipkart: run complete — %d/%d FSNs written to tab '%s' | total time: %dm %ds",
                    total_processed, len(remapped), new_tab, minutes, seconds)

        app.state.flipkart_cron_status.update({
            "last_run_duration_seconds": int(elapsed.total_seconds()),
            "last_run_processed": total_processed,
            "progress": total_processed,
        })

    finally:
        app.state.flipkart_cron_status["is_running"] = False


async def run_scheduled_flipkart_scrape(app) -> None:
    """Called by APScheduler on cron intervals."""
    if app.state.flipkart_cron_status.get("is_running"):
        logger.warning("Flipkart: scheduled scrape skipped — a run is already active (duplicate trigger?)")
        return
    await _run_full_flipkart_scrape(app, tab_prefix="Flipkart_Run", run_type="flipkart_automatic")


async def run_manual_flipkart_trigger(app) -> None:
    """Called when user manually triggers the Flipkart full scrape from the UI."""
    await _run_full_flipkart_scrape(app, tab_prefix="Flipkart_Manual", run_type="flipkart_manual", write_historical=False)


def setup_scheduler(app) -> AsyncIOScheduler | None:
    if os.getenv("CRON_ENABLED", "false").lower() != "true":
        return None

    cron_hour = int(os.getenv("AMAZON_CRON_HOUR", "10"))
    cron_minute = int(os.getenv("AMAZON_CRON_MINUTE", "0"))
    scheduler = AsyncIOScheduler(timezone=IST)

    scheduler.add_job(
        run_scheduled_scrape,
        "cron",
        hour=cron_hour,
        minute=cron_minute,
        args=[app],
        id="amazon_daily_scrape",
        max_instances=1,
        coalesce=True,
    )
    
    flipkart_cron_hour = int(os.getenv("FLIPKART_CRON_HOUR", "9"))
    flipkart_cron_minute = int(os.getenv("FLIPKART_CRON_MINUTE", "15"))
    scheduler.add_job(
        run_scheduled_flipkart_scrape,
        "cron",
        hour=flipkart_cron_hour,
        minute=flipkart_cron_minute,
        args=[app],
        id="flipkart_daily_scrape",
        max_instances=1,
        coalesce=True,
    )
    
    instamart_cron_hour = int(os.getenv("INSTAMART_CRON_HOUR", "12"))
    instamart_cron_minute = int(os.getenv("INSTAMART_CRON_MINUTE", "0"))
    scheduler.add_job(
        run_scheduled_instamart_scrape,
        "cron",
        hour=instamart_cron_hour,
        minute=instamart_cron_minute,
        args=[app],
        id="instamart_daily_scrape",
        max_instances=1,
        coalesce=True,
    )

    blinkit_cron_hour = int(os.getenv("BLINKIT_CRON_HOUR", "9"))
    blinkit_cron_minute = int(os.getenv("BLINKIT_CRON_MINUTE", "30"))
    scheduler.add_job(
        run_scheduled_blinkit_scrape,
        "cron",
        hour=blinkit_cron_hour,
        minute=blinkit_cron_minute,
        args=[app],
        id="blinkit_daily_scrape",
        max_instances=1,
        coalesce=True,
    )

    zepto_cron_hour = int(os.getenv("ZEPTO_CRON_HOUR", "10"))
    zepto_cron_minute = int(os.getenv("ZEPTO_CRON_MINUTE", "0"))
    scheduler.add_job(
        run_scheduled_zepto_scrape,
        "cron",
        hour=zepto_cron_hour,
        minute=zepto_cron_minute,
        args=[app],
        id="zepto_daily_scrape",
        max_instances=1,
        coalesce=True,
    )

    async def _refresh_fkm_cookies_job():
        from flipkart_minutes.cookie_manager import refresh_fkm_cookies, needs_refresh
        try:
            current = getattr(app.state, "fkm_cookies", "")
            if current:
                lock = getattr(app.state, "fkm_cookie_lock", None)
                if lock:
                    async with lock:
                        app.state.fkm_cookies = await refresh_fkm_cookies(app.state.fkm_cookies)
                else:
                    app.state.fkm_cookies = await refresh_fkm_cookies(current)
                logger.info("[FKM] Scheduled cookie refresh complete")
        except Exception as e:
            logger.error("[FKM] Scheduled cookie refresh failed: %s", e)

    scheduler.add_job(
        _refresh_fkm_cookies_job,
        "interval",
        days=14,
        id="fkm_cookie_refresh",
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info("Cron: Amazon daily scrape scheduled at %02d:%02d IST", cron_hour, cron_minute)
    logger.info("Cron: Flipkart daily scrape scheduled at %02d:%02d IST", flipkart_cron_hour, flipkart_cron_minute)
    logger.info("Cron: Instamart daily scrape scheduled at %02d:%02d IST", instamart_cron_hour, instamart_cron_minute)
    logger.info("Cron: Blinkit daily scrape scheduled at %02d:%02d IST", blinkit_cron_hour, blinkit_cron_minute)
    logger.info("Cron: Zepto daily scrape scheduled at %02d:%02d IST", zepto_cron_hour, zepto_cron_minute)
    logger.info("Cron: FK Minutes cookie refresh scheduled every 14 days")
    return scheduler
