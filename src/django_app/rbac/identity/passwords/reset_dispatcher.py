import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor

from django.db import close_old_connections, connections
from utils.logger import logger

_WORKER_COUNT = 2
# Jobs running or waiting, per process. The bound is on delivery latency, not
# memory: at roughly 300 ms per SMTP send on 2 threads, the last of 50 jobs
# waits about 7.5 s for its email. Past that the user is better served by a
# dropped job and a retry than by an email that arrives minutes late.
_MAX_JOBS_IN_FLIGHT = 50
_DROPPED_LOG_INTERVAL_SECONDS = 60


class ConnectionScopedThreadPool(ThreadPoolExecutor):
    """Thread pool whose jobs each run on a database connection of their own.

    Django opens one connection per thread and only closes it at the end of a
    request. A pool thread never sees a request, so without this wrapping
    every worker would keep a connection open for the life of the process,
    possibly one the server has already dropped.
    """

    def submit(self, fn, /, *args, **kwargs):
        return super().submit(_run_with_own_connections, fn, *args, **kwargs)


def _run_with_own_connections(fn, *args, **kwargs):
    close_old_connections()
    try:
        return fn(*args, **kwargs)
    finally:
        connections.close_all()


def _failure_location(error: BaseException) -> str:
    # A frame's location carries no runtime values, unlike the exception
    # message or a traceback with locals, which can hold the email or token.
    frame = traceback.extract_tb(error.__traceback__)[-1]
    return f"{frame.filename}:{frame.lineno} in {frame.name}"


class PasswordResetDispatcher:
    """Runs password-reset jobs off the request thread, with a bounded backlog.

    The anonymous reset request must take the same time whether or not the
    email has an account, so everything that depends on the account (lookup,
    token write, SMTP round trip) runs here instead of in the request.

    This is a deliberate exception to the backend rule against threads for
    I/O: the view is synchronous Django, the project has no task queue, and
    the pool is tiny and bounded, so the cost is two threads per process.

    Delivery is best-effort. When the backlog is full, a new job is dropped
    and logged rather than blocking the request: the endpoint is anonymous and
    throttled, and the user can ask again. On a graceful worker exit (including
    `--max-requests` recycling) `concurrent.futures` runs the queued jobs
    before the process ends; only a SIGKILL, or a drain that outlasts the
    server's graceful timeout, loses them.

    The request path does no I/O that depends on the state of the queue: a
    full backlog costs a semaphore check, and the drop is logged at most once
    per interval, rate-limited in process rather than through the cache.

    A failing job is swallowed and logged by exception type and the line it
    was raised at, nothing more: its message and local variables can hold the
    email address or the raw token. Nothing else would ever see the
    exception, because the request that queued the job has already returned.
    """

    def __init__(self, executor: Executor, max_in_flight: int):
        self._executor = executor
        self._free_slots = threading.BoundedSemaphore(max_in_flight)
        self._drop_log_lock = threading.Lock()
        self._drop_logged_at: float | None = None

    def dispatch(self, job: Callable[[], None]) -> bool:
        """Queue `job` without waiting for it.

        Returns:
            False when the job was not queued: the backlog was full, or the
            executor refused it (it is shutting down).
        """
        if not self._free_slots.acquire(blocking=False):
            self._log_job_dropped()
            return False
        try:
            self._executor.submit(self._run, job)
        except Exception as error:
            # Whatever the executor does, the request still gets its uniform
            # answer; a refused job is a dropped one.
            self._free_slots.release()
            logger.error(
                "password_reset_job_not_queued error_type={} at={}",
                type(error).__name__,
                _failure_location(error),
            )
            return False
        return True

    def _log_job_dropped(self) -> None:
        # A full backlog means a flood of anonymous requests: one line per
        # interval, not one per request.
        now = time.monotonic()
        with self._drop_log_lock:
            if (
                self._drop_logged_at is not None
                and now - self._drop_logged_at < _DROPPED_LOG_INTERVAL_SECONDS
            ):
                return
            self._drop_logged_at = now
        logger.warning(
            "password_reset_job_dropped_backlog_full: repeats suppressed for {}s.",
            _DROPPED_LOG_INTERVAL_SECONDS,
        )

    def _run(self, job: Callable[[], None]) -> None:
        try:
            job()
        except Exception as error:
            # One line, because `utils.logger` cuts messages at 200 characters.
            logger.error(
                "password_reset_job_failed error_type={} at={}",
                type(error).__name__,
                _failure_location(error),
            )
        finally:
            self._free_slots.release()


# The one dispatcher of this process: pool and backlog bound live together, so
# the bound holds however many services are built. Threads start lazily, on
# the first submit, so a process that never dispatches never starts them.
# `PasswordRecoveryService` reads this attribute at dispatch time, which lets
# the test suite replace it with an inline dispatcher (tests/conftest.py).
default_dispatcher = PasswordResetDispatcher(
    executor=ConnectionScopedThreadPool(
        max_workers=_WORKER_COUNT, thread_name_prefix="password-reset"
    ),
    max_in_flight=_MAX_JOBS_IN_FLIGHT,
)
