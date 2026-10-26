import sys

from loguru import logger

__all__ = ["configure_logging"]


def configure_logging(component: str) -> None:
    """Replace loguru's handlers with one stdout handler that hides variable values.

    `diagnose=False` matters: with loguru's default, a traceback prints the value of every
    variable on the failing lines, which would write the node key and plugin secrets into
    the container's log. `enqueue=False` keeps loguru from starting a thread, which the
    launcher must not have: it forks.
    """
    logger.remove()
    logger.add(
        sys.stdout,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | " + component + " | {message}",
        diagnose=False,
        backtrace=False,
        enqueue=False,
    )
