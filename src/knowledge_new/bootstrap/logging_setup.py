import sys

import settings
from loguru import logger

__all__ = ["configure_logging"]


def configure_logging() -> None:
    """Replace every loguru sink with one stderr sink at `KNOWLEDGE_LOG_LEVEL`."""
    logger.remove()
    logger.add(sys.stderr, level=settings.LOG_LEVEL)
