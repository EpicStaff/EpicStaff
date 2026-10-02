"""Stress-test checkpoint logger (stress-test branch only, never merged)."""

import json
import os
import time
from contextvars import ContextVar

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

_warned = False

# Agent only: the LLM client has no request in scope, so RequestHandler parks the
# run's correlation_id here (per asyncio task) for the llm_start/llm_end lines.
bench_correlation_id: ContextVar[str | None] = ContextVar("bench_correlation_id", default=None)
# Crew only: set once per session task in run_session, so code without a session
# in scope (agent/sandbox dispatch, subgraph nodes) still gets tagged.
bench_session_id: ContextVar[int | None] = ContextVar("bench_session_id", default=None)


def bench_mark(session_id: int | None, checkpoint: str, **extra) -> None:
    """Append one checkpoint line to `<BENCH_DIR>/<BENCH_SERVICE>.jsonl`.

    Never raises: the first failure is logged, every failure is swallowed, so the
    benchmark can never break a session. One `open("a")` + one `write` per line keeps
    lines whole across async tasks and threads without a lock (lines < PIPE_BUF).
    """
    global _warned
    try:
        service = os.environ.get("BENCH_SERVICE", "unknown")
        if session_id is None:
            session_id = bench_session_id.get()
        line = json.dumps(
            {
                "ts": time.time(),
                "service": service,
                "session_id": session_id,
                "checkpoint": checkpoint,
                **extra,
            },
            default=str,
        )
        path = os.path.join(os.environ.get("BENCH_DIR", "/app/bench"), f"{service}.jsonl")
        with open(path, "a") as bench_file:
            bench_file.write(line + "\n")
    except Exception as error:
        if not _warned:
            _warned = True
            try:
                logger.warning("bench_mark failed: {}".format(error))
            except Exception:
                pass
