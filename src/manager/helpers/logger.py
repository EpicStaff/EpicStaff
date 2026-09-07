from loguru import logger
import sys

logger.remove()
logger.add(sys.stdout, format="{time} {level} {message}", level="INFO")
logger.add("logs/file.log", rotation="1 MB", compression="zip")


def log_exception(exc_type, exc_value, exc_traceback):
    logger.exception("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = log_exception
