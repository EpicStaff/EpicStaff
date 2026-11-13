"""Background runners and their supervision, shared by both processes.

The manager's Litestar lifespan and the standalone worker both start their loops as
supervised tasks: a runner that ends, for any reason, takes its process down so the
container restarts it, instead of the process living on without a part of its pipeline.
"""

import asyncio
import os
import signal
from collections.abc import Callable
from typing import Protocol

from loguru import logger

__all__ = ["Runner", "supervise", "terminate_process"]


class Runner(Protocol):
    """A background loop the composition root starts as a supervised task."""

    async def run(self) -> None: ...


def terminate_process() -> None:
    """Take the process down so the container's restart policy brings it back clean.

    SIGTERM rather than an exit: uvicorn shuts down gracefully on it, running the
    shutdown hooks, and the standalone worker simply dies into a restart. Also the
    worker transports' last resort when results cannot be delivered at all: the restart
    surfaces as a new boot id, and the manager fails the stranded jobs fast.
    """
    os.kill(os.getpid(), signal.SIGTERM)


def supervise(task: asyncio.Task, *, stop: Callable[[], None] = terminate_process) -> None:
    """Stop the process when `task` ends for any reason other than being cancelled.

    The runners loop forever, so any end -- an exception or a plain return -- means a
    part of the pipeline is gone. Logged with the runner's name and the exception type
    only: the exception's text may quote a job.
    """

    def on_done(finished: asyncio.Task) -> None:
        if finished.cancelled():
            return
        error = finished.exception()
        logger.critical(
            "Runtime runner '{}' stopped ({}); shutting the sandbox down",
            finished.get_name(),
            "returned" if error is None else type(error).__name__,
        )
        stop()

    task.add_done_callback(on_done)
