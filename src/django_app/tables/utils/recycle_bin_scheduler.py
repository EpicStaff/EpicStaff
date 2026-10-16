"""Run the recycle-bin purge once a day, in exactly one web worker per host."""

import tempfile
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from django.db import close_old_connections
from filelock import FileLock, Timeout
from utils.logger import logger

_PURGE_JOB_ID = "recycle_bin_purge"

# Held for the lifetime of the owner process, so the lock is released only
# when the process exits.
_purge_owner_lock: FileLock | None = None


def _lock_path() -> Path:
    return Path(tempfile.gettempdir()) / "epicstaff_recycle_bin_purge.lock"


def run_recycle_bin_purge() -> None:
    """Purge expired recycle-bin items. Logs and swallows errors so the scheduler keeps running."""
    from tables.services.recycle_bin.purge_service import PurgeService

    close_old_connections()  # a scheduler thread may hold a stale connection
    try:
        counts = PurgeService.purge_expired()
        logger.info("Recycle bin purge finished: {}", counts or "nothing to purge")
    except Exception:
        logger.exception("Recycle bin purge failed")
    finally:
        close_old_connections()


def start_recycle_bin_purge_if_owner() -> bool:
    """Start the daily purge if this process wins the per-host file lock. Returns True if it did.

    Several web workers on one host share the temp dir, so one of them runs the
    job. Separate hosts or containers each run their own; that's safe, because
    purge_expired skips rows another process has locked.
    """
    global _purge_owner_lock

    lock = FileLock(str(_lock_path()))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        logger.info("Recycle bin purge already owned by another worker on this host.")
        return False

    _purge_owner_lock = lock
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        run_recycle_bin_purge,
        trigger="cron",
        hour=3,
        minute=0,
        id=_PURGE_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("Scheduled the daily recycle bin purge at 03:00 server time")
    return True
