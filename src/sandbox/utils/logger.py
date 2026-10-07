import sys

import settings
from loguru import logger

MAX_LOG_LENGTH = 350


def truncate_filter(record):
    msg = record["message"]
    if len(msg) > MAX_LOG_LENGTH:
        record["message"] = msg[:MAX_LOG_LENGTH] + "..."
    return True


logger.remove()
logger.add(
    sys.stdout, format="{time} {level} {message}", level=settings.LOG_LEVEL, filter=truncate_filter
)
