"""Sets up the single logging sink the service writes through."""

import inspect
import logging
import sys

import settings
from loguru import logger
from src.shared.bench_log import add_bench_sink, without_bench

__all__ = ["configure_logging"]

FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"

INTERCEPTED = ("uvicorn", "uvicorn.access", "uvicorn.error", "litestar", "piccolo", "httpx")


class InterceptHandler(logging.Handler):
    """Re-emits a stdlib record through loguru at the matching level."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame is not None and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging() -> None:
    """Point loguru and the stdlib loggers at one sink at `settings.LOG_LEVEL`.

    Uvicorn, Litestar and Piccolo log through the standard library, so without the
    intercept the service would write two formats to stderr and honour the level on
    only one of them. Litestar's own "Uncaught exception" record arrives this way.

    `diagnose` stays off: it appends the local variables of every frame to a
    traceback, and the frames here hold job secrets and storage credentials.

    At BENCH (or DEBUG/TRACE) benchmark checkpoints go to the same stream as JSON lines
    instead of through the normal format; see src/shared/bench_log.py.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=FORMAT,
        filter=without_bench(),
        backtrace=False,
        diagnose=False,
    )
    add_bench_sink(sys.stderr, settings.LOG_LEVEL)

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in INTERCEPTED:
        intercepted = logging.getLogger(name)
        intercepted.handlers = [InterceptHandler()]
        intercepted.propagate = False
