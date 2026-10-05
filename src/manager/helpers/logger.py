import sys

import settings
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{time} {level} {message}", level=settings.LOG_LEVEL)
logger.add("logs/file.log", level=settings.LOG_LEVEL, rotation="1 MB", compression="zip")


def log_exception(exc_type, exc_value, exc_traceback):
    logger.exception("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = log_exception
