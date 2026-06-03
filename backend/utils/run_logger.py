"""Persistent run logger — stores scrape run metadata in a JSON file."""

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

_lock = Lock()


def _read_logs() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        logger.warning("Corrupt log file — resetting")
        return []


def _write_logs(logs: list[dict]) -> None:
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2, default=str)


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
        logs = _read_logs()
        logs.insert(0, entry)  # newest first
        _write_logs(logs)
    logger.info("Log created: run_id=%s type=%s total=%d", run_id, run_type, total_asins)
    return run_id


def update_progress(run_id: str, success_count: int, failed_count: int) -> None:
    """Update counts on an in-progress run."""
    with _lock:
        logs = _read_logs()
        for entry in logs:
            if entry["run_id"] == run_id:
                entry["success_count"] = success_count
                entry["failed_count"] = failed_count
                break
        _write_logs(logs)


def complete_log(
    run_id: str,
    success_count: int,
    failed_count: int,
    sheet_tab: Optional[str] = None,
) -> None:
    """Mark a run as completed."""
    with _lock:
        logs = _read_logs()
        for entry in logs:
            if entry["run_id"] == run_id:
                entry["completed_at"] = datetime.now(IST).isoformat()
                entry["success_count"] = success_count
                entry["failed_count"] = failed_count
                entry["sheet_tab"] = sheet_tab
                entry["status"] = "completed"
                break
        _write_logs(logs)
    logger.info("Log completed: run_id=%s success=%d failed=%d tab=%s",
                run_id, success_count, failed_count, sheet_tab)


def fail_log(run_id: str, error_message: str) -> None:
    """Mark a run as failed."""
    with _lock:
        logs = _read_logs()
        for entry in logs:
            if entry["run_id"] == run_id:
                entry["completed_at"] = datetime.now(IST).isoformat()
                entry["status"] = "failed"
                entry["error"] = error_message
                break
        _write_logs(logs)
    logger.error("Log failed: run_id=%s error=%s", run_id, error_message)


def get_all_logs() -> list[dict]:
    """Return all log entries, newest first."""
    with _lock:
        return _read_logs()
