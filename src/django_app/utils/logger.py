import traceback
from loguru import logger
import sys


MAX_LOG_LENGTH = 200


def truncate_filter(record):
    msg = record["message"]
    if len(msg) > MAX_LOG_LENGTH:
        record["message"] = msg[:MAX_LOG_LENGTH] + "..."
    return True


logger.remove()
logger.add(
    sys.stdout, format="{time} {level} {message}", level="INFO", filter=truncate_filter
)
# logger.add("logs/file.log", rotation="1 MB", compression="zip")
# TODO: setup saving and rotating log files with DEBUG level logs


def log_exception(exc_type, exc_value, exc_traceback):
    formatted_traceback = "".join(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    logger.opt(exception=exc_value).exception(formatted_traceback)


sys.excepthook = log_exception
