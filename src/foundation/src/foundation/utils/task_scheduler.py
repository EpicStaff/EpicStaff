"""A simple in-process scheduler for async jobs registered with ``@schedule``."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from loguru import logger

__all__ = ["schedule", "start", "stop"]


type Work = Callable[[], Awaitable]


@dataclass(frozen=True)
class ScheduleEntry:
    """A registered unit of async work, optionally repeating on an interval."""

    work: Work
    interval: float | int | None = None

    def __post_init__(self):
        if not callable(self.work):
            raise TypeError("Must be callable.")

        if not isinstance(self.interval, float | int | None):
            raise TypeError("Interval must be float or None")
        elif self.interval is not None and self.interval <= 0:
            raise ValueError("Interval must be > 0.")

    @property
    def is_interval(self) -> bool:
        """Whether this entry repeats on an interval rather than running once."""
        return self.interval is not None


_is_run = False
_schedule: list[ScheduleEntry] = []
_running: set[asyncio.Task] = set()


def schedule(func: Work | None = None, /, *, interval: float | None = None):
    """Register a coroutine function as a scheduled job.

    Usable bare (``@schedule``) for a one-shot job, or with ``interval`` seconds
    (``@schedule(interval=5)``) to repeat. Returns the function unchanged.
    """

    def decorator(func: Work):
        _schedule.append(ScheduleEntry(work=func, interval=interval))
        return func

    if func is not None:
        return decorator(func)
    return decorator


async def start():
    """Launch every registered job as a background task; a no-op if already started."""
    global _is_run
    if _is_run:
        return
    _is_run = True

    for job in _schedule:
        if job.is_interval:
            coro = run_in_interval(job.work, cast(float, job.interval))
        else:
            coro = run(job.work)
        task = asyncio.create_task(coro)
        task.add_done_callback(_running.discard)
        _running.add(task)


async def stop():
    """Cancel all running jobs and wait for them to finish; a no-op if not started."""
    global _is_run
    if not _is_run:
        return
    for task in _running:
        task.cancel()
    await asyncio.gather(*_running, return_exceptions=True)
    _is_run = False


async def run(func: Work):
    """Run ``func`` once, logging any exception instead of propagating it."""
    try:
        await func()
    except Exception:
        logger.exception("Error occurs during run work: {}", func.__name__)


async def run_in_interval(func: Work, interval: float):
    """Run ``func`` repeatedly, sleeping ``interval`` seconds between runs."""
    while True:
        await run(func)
        await asyncio.sleep(interval)
