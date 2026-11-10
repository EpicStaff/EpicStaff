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
from collections.abc import Callable
from concurrent.futures import Executor

from rbac.identity.passwords.failure_description import describe_failure
from rbac.identity.passwords.reset_dispatcher import ConnectionScopedThreadPool
from utils.logger import logger

_MAX_JOBS_IN_FLIGHT = 100
_free_slots = threading.BoundedSemaphore(_MAX_JOBS_IN_FLIGHT)
# Read at each call, so the test suite can run the jobs inline. Its thread starts on the
# first job, so a process that never records one starts none.
executor: Executor = ConnectionScopedThreadPool(max_workers=1, thread_name_prefix="user-audit")


def run_off_request(job: Callable[[], None]) -> None:
    """Queue `job` on the worker, on a database connection of its own, without waiting.

    Never raises. A job past the backlog, or one the executor refuses (shutting down), is
    dropped and logged.
    """
    if not _free_slots.acquire(blocking=False):
        logger.warning("Dropped a user action job: the backlog is full")
        return
    try:
        executor.submit(_run, job)
    except Exception as error:
        _free_slots.release()
        logger.error("User action job not queued {}", describe_failure(error))


def _run(job: Callable[[], None]) -> None:
    try:
        job()
    except Exception as error:
        # Only where it failed: a sign-in job's message can hold the email it looked up.
        logger.error("User action job failed {}", describe_failure(error))
    finally:
        _free_slots.release()
