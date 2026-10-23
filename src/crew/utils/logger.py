import sys
import traceback
from types import TracebackType

import settings
from loguru import logger
from src.shared.bench_log import add_bench_sink, without_bench

logger.remove()
# `diagnose=False` matters: with loguru's default, a `logger.exception` traceback prints
# the value of every identifier on each displayed source line. Crew's frames carry the
# sandbox submit body, so a default sink would write `secrets` plaintext and
# `storage_credentials.secret_key` to stdout on any failed submit.
logger.add(
    sys.stdout,
    format="{time} {level} {message}",
    level=settings.LOG_LEVEL,
    filter=without_bench(),
    diagnose=False,
    backtrace=False,
)
# The bench sink renders checkpoint records through `bench_json` and never an
# exception, so it needs no such guard.
add_bench_sink(sys.stdout, settings.LOG_LEVEL)


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
