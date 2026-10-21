"""Run the plugin platform's scheduled maintenance in exactly one web worker per host.

The retention tick runs every 60 s (`RetentionService`), the housekeeping every hour
(`HousekeepingService`). Several web workers on one host share the temp dir, so the one that
wins the file lock runs both; separate hosts or containers each run their own, which is safe
because every step skips rows another process holds. Started whatever `PLUGINS_ENABLED`
says. Tests call the services directly; the scheduler never starts in them.
"""

import tempfile
from collections.abc import Callable
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from django.db import close_old_connections
from filelock import FileLock, Timeout
from utils.logger import logger

RETENTION_INTERVAL_SECONDS = 60
HOUSEKEEPING_INTERVAL_SECONDS = 3600

# Held for the lifetime of the owner process, so the lock is released only when it exits.
_owner_lock: FileLock | None = None


def _lock_path() -> Path:
    return Path(tempfile.gettempdir()) / "epicstaff_plugin_retention.lock"


def run_retention_tick() -> None:
    """One retention tick; logs and swallows errors so the scheduler keeps running."""
    from plugins.lifecycle.retention_service import RetentionService

    _run_logged("Plugin retention tick", lambda: RetentionService().run())


def run_housekeeping() -> None:
    """One housekeeping run; logs and swallows errors so the scheduler keeps running."""
    from plugins.lifecycle.housekeeping_service import HousekeepingService

    _run_logged("Plugin housekeeping", lambda: HousekeepingService().run())


def _run_logged(name: str, job: Callable[[], object]) -> None:
    close_old_connections()  # a scheduler thread may hold a stale connection
    try:
        job()
    except Exception:  # a background job: one failed run must not end the schedule
        logger.exception("{name} failed", name=name)
    finally:
        close_old_connections()


def start_plugin_retention_if_owner() -> bool:
    """Start both jobs if this process wins the per-host file lock. Returns True if it did."""
    global _owner_lock

    lock = FileLock(str(_lock_path()))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        logger.info("Plugin retention already owned by another worker on this host.")
        return False

    _owner_lock = lock
    scheduler = BackgroundScheduler(daemon=True)
    for job, job_id, seconds in (
        (run_retention_tick, "plugin_retention", RETENTION_INTERVAL_SECONDS),
        (run_housekeeping, "plugin_housekeeping", HOUSEKEEPING_INTERVAL_SECONDS),
    ):
        scheduler.add_job(
            job,
            trigger="interval",
            seconds=seconds,
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=RETENTION_INTERVAL_SECONDS,
        )
    scheduler.start()
    logger.info("Scheduled the plugin retention tick and the hourly plugin housekeeping")
    return True
