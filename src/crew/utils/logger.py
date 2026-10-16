import sys
import traceback
from types import TracebackType

import settings
from loguru import logger
from src.shared.bench_log import add_bench_sink, without_bench

logger.remove()
logger.add(
    sys.stdout, format="{time} {level} {message}", level=settings.LOG_LEVEL, filter=without_bench()
)
add_bench_sink(sys.stdout, settings.LOG_LEVEL)
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
