import sys

import settings
from loguru import logger
from src.shared.bench_log import add_bench_sink, without_bench

MAX_LOG_LENGTH = 350


def truncate_filter(record):
    msg = record["message"]
    if len(msg) > MAX_LOG_LENGTH:
        record["message"] = msg[:MAX_LOG_LENGTH] + "..."
    return True


logger.remove()
logger.add(
    sys.stdout,
    format="{time} {level} {message}",
    level=settings.LOG_LEVEL,
    filter=without_bench(truncate_filter),
)
add_bench_sink(sys.stdout, settings.LOG_LEVEL)
