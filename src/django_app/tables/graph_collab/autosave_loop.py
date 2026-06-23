"""
Global autosave loop for collaborative graph editing.

A single asyncio task runs inside the ASGI worker process (GUNICORN_WORKERS=1).
It wakes up every AUTOSAVE_FLUSH_INTERVAL_SECONDS, iterates all graphs that
currently have active editors, and flushes any that have unsaved changes.

The task is started lazily (and idempotently) on the first WebSocket connect via
``ensure_autosave_loop_running()``.  It lives for the lifetime of the process —
an empty pass when there are no active editors is a no-op.

This replaces the per-connection autosave loops (which ran once per consumer and
required a Redis NX lock to deduplicate flushes across connections on the same
graph).  Because there is now a single flusher per process, no distributed lock
is needed.
"""

import asyncio

from tables.graph_collab.constants import AUTOSAVE_FLUSH_INTERVAL_SECONDS
from tables.graph_collab.flush_service import FlushStatus, flush_service
from tables.graph_collab.notifications import anotify_graph_saved, anotify_save_failed
from tables.graph_collab.presence_service import presence_service
from utils.logger import logger

_autosave_task: asyncio.Task | None = None


def ensure_autosave_loop_running() -> None:
    """Start the global autosave loop if it is not already running.

    Synchronous and idempotent — safe to call on every WebSocket connect.
    There is no ``await`` between the guard check and the assignment, so in a
    single-threaded asyncio event loop this is race-free: no two coroutines can
    interleave between the ``if`` and the ``=``.
    """
    global _autosave_task
    if _autosave_task is not None and not _autosave_task.done():
        return
    _autosave_task = asyncio.ensure_future(_global_autosave_loop())
    logger.info("Global autosave loop started")


async def _global_autosave_loop() -> None:
    """Run forever, flushing dirty graphs every AUTOSAVE_FLUSH_INTERVAL_SECONDS."""
    try:
        while True:
            await asyncio.sleep(AUTOSAVE_FLUSH_INTERVAL_SECONDS)
            await _autosave_pass()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error(
            "Global autosave loop crashed: {} — loop will restart on next connect", exc
        )


async def _autosave_pass() -> None:
    """Flush all dirty graphs in a single autosave pass.

    Each graph is handled in its own try/except so a failure on one graph
    cannot abort the pass for all others.
    """
    graph_ids = presence_service.active_graph_ids()
    for graph_id in graph_ids:
        try:
            outcome = await flush_service.flush_if_dirty(graph_id)
            if outcome.status is FlushStatus.SAVED:
                result = outcome.result
                await anotify_graph_saved(
                    graph_id=graph_id,
                    new_save_version=result.new_save_version,
                    saved_at=result.saved_at,
                    user=None,
                    temp_id_map=result.temp_id_map,
                )
            elif outcome.status is FlushStatus.FAILED and outcome.persistent:
                await anotify_save_failed(
                    graph_id=graph_id,
                    reason=outcome.failure_reason or "db_error",
                )
        except Exception as exc:
            logger.error(
                "Autosave pass: unhandled error for graph {}: {}", graph_id, exc
            )
