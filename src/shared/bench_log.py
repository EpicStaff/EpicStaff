"""BENCH checkpoint logging: one JSON line per performance checkpoint.

Checkpoints are records at level 15 ("BENCH", between DEBUG and INFO), registered for loguru and
for stdlib `logging`. A service whose <SERVICE>_LOG_LEVEL is BENCH (or DEBUG/TRACE) writes every
checkpoint as one compact JSON line through `add_bench_sink`; its normal sink drops them through
`without_bench`, so nothing is printed twice. At the default INFO level nothing changes.

A line is `{"bench": 1, "ts": <unix seconds>, "checkpoint": <name>, ...}` followed by the
record's other extra fields (the call's keyword arguments and any bound context, except keys that
start with "_"). Checkpoint names and fields are a contract with whatever reads these lines;
change one only together with its reader:
django_app request_received, session_created, published; crew received, slot_acquired, compiled,
node_start, node_end, agent_dispatched, sandbox_dispatched, session_end; agent request_consumed,
llm_start, llm_end, sandbox_dispatched, result_published; sandbox exec_start, exec_end;
sandbox_new exec_received, exec_held (venv_id), exec_queued (queued), exec_start (running),
exec_launched, exec_exited (returncode, timed_out), exec_end (returncode), exec_expired
(waited_s), exec_published (outcome: ok, failed, venv_failed, dispatch_failed or overloaded),
and, every 5 s and without session_id or execution_id, sandbox_gate (running, floor,
max_concurrent, cpu_busy_percent and memory_used_percent -- None when unreadable --, queued
-- running ones included --, held, drain_rate -- None on a cold start --, and the 503s since
the previous sample: refused_cap, refused_prediction, refused_held_cap, refused_in_progress);
crew and agent also sandbox_rejected (attempt, retry_after_s), on each 503 followed by a
retry, and sandbox_lost, when the sandbox no longer knows an execution awaiting its result.
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
