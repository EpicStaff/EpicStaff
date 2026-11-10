"""Runs user-action capture that must not run on the request thread.

A failed sign-in is answered with the same 401 whether or not the account exists, but
finding the account and recording in each of its orgs takes time only when it does. Done
before the response, that time tells a caller which emails have accounts.

A deliberate exception to the backend rule against threads for I/O, as in
`rbac.identity.passwords.reset_dispatcher`: the views are synchronous Django and the
project has no task queue. One worker, a bounded backlog: past it a job is dropped and
logged, never queued without limit for an anonymous caller.
"""

import threading
import time
from collections.abc import Callable
from concurrent.futures import Executor

from rbac.identity.passwords.failure_description import describe_failure
from rbac.identity.passwords.reset_dispatcher import ConnectionScopedThreadPool
from utils.logger import logger

_MAX_JOBS_IN_FLIGHT = 100
_DROPPED_LOG_INTERVAL_SECONDS = 60
_free_slots = threading.BoundedSemaphore(_MAX_JOBS_IN_FLIGHT)
_drop_log_lock = threading.Lock()
_drop_logged_at: float | None = None
# Read at each call, so the test suite can run the jobs inline. Its thread starts on the
# first job, so a process that never records one starts none.
executor: Executor = ConnectionScopedThreadPool(max_workers=1, thread_name_prefix="user-audit")


def run_off_request(job: Callable[[], None]) -> None:
    """Queue `job` on the worker, on a database connection of its own, without waiting.

    Never raises. A job past the backlog, or one the executor refuses (shutting down), is
    dropped and logged; a full backlog is logged once per interval, not once per job.
    `job` handles and logs its own failures, without the values it holds (a sign-in job
    holds a login email): nothing reads its result.
    """
    if not _free_slots.acquire(blocking=False):
        _log_job_dropped()
        return
    try:
        executor.submit(_run, job)
    except Exception as error:
        _free_slots.release()
        logger.error("User action job not queued {}", describe_failure(error))


def _log_job_dropped() -> None:
    # A full backlog means a flood of failed sign-ins: one line per interval, not one each.
    global _drop_logged_at
    now = time.monotonic()
    with _drop_log_lock:
        if _drop_logged_at is not None and now - _drop_logged_at < _DROPPED_LOG_INTERVAL_SECONDS:
            return
        _drop_logged_at = now
    logger.warning(
        "Dropped a user action job: the backlog is full; repeats suppressed for {}s",
        _DROPPED_LOG_INTERVAL_SECONDS,
    )


def _run(job: Callable[[], None]) -> None:
    try:
        job()
    finally:
        _free_slots.release()
