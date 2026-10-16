import sys
import traceback
from types import TracebackType

import settings
from loguru import logger


def _validated_log_level(configured_level: str | None) -> str:
    level = (configured_level or "").upper()
    try:
        logger.level(level)
    except ValueError:
        raise ValueError(
            f"CREW_LOG_LEVEL={configured_level!r} is not a log level; use one of "
            "TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL."
        ) from None
    return level


logger.remove()
logger.add(
    sys.stdout,
    format="{time} {level} {message}",
    level=_validated_log_level(settings.LOG_LEVEL),
)


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
