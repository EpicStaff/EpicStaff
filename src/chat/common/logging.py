import sys

from loguru import logger

__all__ = ["configure_logging"]


def configure_logging(level: str) -> None:
    """Replace loguru's handlers with one stderr handler that hides variable values.

    `diagnose=False` matters: with loguru's default, exception tracebacks print the value of
    every variable on the failing lines, which writes tokens, secrets and message text into
    the logs. Calling it again replaces the handler, so it is safe per `create_app()`.
    """
    logger.remove()
    logger.add(sys.stderr, level=level, diagnose=False, backtrace=False, enqueue=False)
