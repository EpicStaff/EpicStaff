import sys

import settings
from loguru import logger

__all__ = ["configure_logging"]


def configure_logging() -> None:
    """Replace every loguru sink with one stderr sink at `KNOWLEDGE_LOG_LEVEL`.

    The sink sets `diagnose=False` because loguru's default handler prints every
    frame's variable values in tracebacks, which writes the caller's provider keys
    to the log whenever an embedder call fails.
    """
    logger.remove()
    logger.add(sys.stderr, level=settings.LOG_LEVEL, diagnose=False)
