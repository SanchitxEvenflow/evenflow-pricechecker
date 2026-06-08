"""Persistent run logger — stores scrape run metadata in a JSON file.

Optimization: logs are kept in-memory during a run. The JSON file is only
read once on startup and written on create/complete/fail — NOT on every
progress tick. This eliminates the O(n) read+write per PID that was
previously the #1 disk I/O bottleneck during large scrape runs.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
LOG_FILE = Path(os.getenv("SCRAPER_LOG_FILE", "scraper_logs.json"))
MAX_LOG_ENTRIES = 500  # Cap to prevent unbounded growth (Issue #11)

_lock = Lock()
_cache: list[dict] | None = None  # In-memory cache, loaded lazily


def _ensure_cache() -> list[dict]:
    """Load the cache from disk if it hasn't been loaded yet."""
    global _cache
    if _cache is None:
        if LOG_FILE.exists():
            try:
                with open(LOG_FILE, "r") as f:
                    _cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning("Corrupt log file — resetting")
                _cache = []
        else:
            _cache = []
    return _cache


def _persist() -> None:
    """Write the in-memory cache to disk. Must be called under _lock."""
    if _cache is None:
        return
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(_cache[:MAX_LOG_ENTRIES], f, indent=2, default=str)
    except IOError:
        logger.exception("Failed to write log file")


def create_log(run_type: str, total_asins: int) -> str:
    """Create a new in-progress log entry. Returns the run_id."""
    run_id = str(uuid.uuid4())[:8]
    entry = {
        "run_id": run_id,
        "type": run_type,  # "automatic" or "manual"
        "triggered_at": datetime.now(IST).isoformat(),
        "completed_at": None,
        "total_asins": total_asins,
        "success_count": 0,
        "failed_count": 0,
        "sheet_tab": None,
        "status": "in_progress",
    }
    with _lock:
        logs = _ensure_cache()
        logs.insert(0, entry)  # newest first
        _persist()
    logger.info("Log created: run_id=%s type=%s total=%d", run_id, run_type, total_asins)
    return run_id


def update_progress(run_id: str, success_count: int, failed_count: int) -> None:
    """Update counts on an in-progress run. Memory-only — no disk I/O."""
    with _lock:
        logs = _ensure_cache()
        for entry in logs:
            if entry["run_id"] == run_id:
                entry["success_count"] = success_count
                entry["failed_count"] = failed_count
                break
        # NO _persist() call — this is the key optimization.
        # Progress is transient; it's written to disk on complete/fail.


def complete_log(
    run_id: str,
    success_count: int,
    failed_count: int,
    sheet_tab: Optional[str] = None,
) -> None:
    """Mark a run as completed and persist to disk."""
    with _lock:
        logs = _ensure_cache()
        for entry in logs:
            if entry["run_id"] == run_id:
                entry["completed_at"] = datetime.now(IST).isoformat()
                entry["success_count"] = success_count
                entry["failed_count"] = failed_count
                entry["sheet_tab"] = sheet_tab
                entry["status"] = "completed"
                break
        _persist()
    logger.info("Log completed: run_id=%s success=%d failed=%d tab=%s",
                run_id, success_count, failed_count, sheet_tab)


def fail_log(run_id: str, error_message: str) -> None:
    """Mark a run as failed and persist to disk."""
    with _lock:
        logs = _ensure_cache()
        for entry in logs:
            if entry["run_id"] == run_id:
                entry["completed_at"] = datetime.now(IST).isoformat()
                entry["status"] = "failed"
                entry["error"] = error_message
                break
        _persist()
    logger.error("Log failed: run_id=%s error=%s", run_id, error_message)


def get_all_logs() -> list[dict]:
    """Return all log entries, newest first."""
    with _lock:
        return list(_ensure_cache())
