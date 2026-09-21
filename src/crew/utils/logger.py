import sys
import traceback
from types import TracebackType

from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{time} {level} {message}", level="INFO")
# logger.add("logs/file.log", rotation="1 MB", compression="zip")


def log_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType,
):
    # todo: send error to redis
    formatted_traceback = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    logger.exception(
        f"Uncaught exception\n{formatted_traceback}",
        exc_info=(exc_type, exc_value, exc_traceback),
    )


sys.excepthook = log_exception
