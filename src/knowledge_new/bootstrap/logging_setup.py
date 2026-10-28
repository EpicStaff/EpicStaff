import copy
import logging
import sys

import settings
from litestar.logging.config import LoggingConfig, default_handlers
from loguru import logger

__all__ = ["build_litestar_logging_config", "configure_logging"]


def configure_logging() -> None:
    """Replace every loguru sink with one stderr sink at `KNOWLEDGE_LOG_LEVEL`.

    The sink sets `diagnose=False` because loguru's default handler prints every
    frame's variable values in tracebacks, which writes the caller's provider keys
    to the log whenever an embedder call fails.
    """
    logger.remove()
    logger.add(sys.stderr, level=settings.LOG_LEVEL, diagnose=False)


def build_litestar_logging_config() -> LoggingConfig:
    """Build a LoggingConfig for Litestar with LOG_LEVEL applied to all handlers.

    `root`'s level is set to `max(level_number, logging.INFO)` — never below INFO.
    Without that floor, `KNOWLEDGE_LOG_LEVEL=DEBUG` would lower the *effective*
    level inherited by every third-party logger that never calls its own
    `setLevel()`.

    Returns:
        LoggingConfig configured with default handlers at the specified LOG_LEVEL.
    """
    handlers = copy.deepcopy(default_handlers)
    level_number = logger.level(settings.LOG_LEVEL).no
    for handler in handlers.values():
        handler["level"] = level_number

    return LoggingConfig(
        handlers=handlers,
        root={"handlers": ["queue_listener"], "level": max(level_number, logging.INFO)},
    )
