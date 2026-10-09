"""BENCH checkpoint logging for the benchmark in benchmark/ (see benchmark/README.md).

Checkpoints are records at level 15 ("BENCH", between DEBUG and INFO), registered for loguru and
for stdlib `logging`. A service whose <SERVICE>_LOG_LEVEL is BENCH (or DEBUG/TRACE) writes every
checkpoint as one compact JSON line through `add_bench_sink`; its normal sink drops them through
`without_bench`, so nothing is printed twice. At the default INFO level nothing changes.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

from loguru import logger

BENCH_LEVEL = 15
BENCH_LEVEL_NAME = "BENCH"

try:
    logger.level(BENCH_LEVEL_NAME)
except ValueError:
    logger.level(BENCH_LEVEL_NAME, no=BENCH_LEVEL, color="<cyan>")
logging.addLevelName(BENCH_LEVEL, BENCH_LEVEL_NAME)


def without_bench(inner: Callable[[Any], bool] | None = None) -> Callable[[Any], bool]:
    """Filter for a service's normal sink: drop BENCH records, then apply `inner` if given."""

    def keep(record) -> bool:
        if record["level"].no == BENCH_LEVEL:
            return False
        return inner(record) if inner else True

    return keep


def bench_json(record) -> str:
    """Loguru format function: the checkpoint's extra fields as one JSON line."""
    payload = {"bench": 1, "ts": record["time"].timestamp()}
    payload.update(
        (key, value) for key, value in record["extra"].items() if not key.startswith("_")
    )
    record["extra"]["_bench_json"] = json.dumps(payload, default=str)
    return "{extra[_bench_json]}\n"


def add_bench_sink(sink: Any, level: str | int) -> int | None:
    """Add the JSON checkpoint sink when the service's level lets BENCH records through."""
    level_no = level if isinstance(level, int) else logger.level(level).no
    if level_no > BENCH_LEVEL:
        return None
    return logger.add(
        sink,
        level=BENCH_LEVEL,
        format=bench_json,
        filter=lambda record: record["level"].no == BENCH_LEVEL,
    )
