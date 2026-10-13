import sys

from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{time} {level} {message}", level="INFO")


def log_exception(exc_type, exc_value, exc_traceback):
    logger.exception("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = log_exception
