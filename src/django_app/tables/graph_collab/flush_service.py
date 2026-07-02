"""
Autosave flush service for collaborative graph editing.

GraphFlushService.flush() is the single choke-point called by all three
autosave triggers (periodic task, last-leave, backstop).  It reads the current
live snapshot from Redis, runs it through GraphBulkSaveInputSerializer and
GraphBulkSaveService, then remaps temp ids back into the snapshot so the next
flush treats newly-created nodes as updates rather than re-creating them.

Flush semantics are *best-effort*: validation failures and version conflicts are
logged and swallowed — the caller receives a FlushOutcome with status FAILED.
Only unexpected exceptions (e.g. Redis transport errors) may propagate.

FlushOutcome.status is always one of:
  SAVED           — snapshot persisted; new_save_version / temp_id_map / saved_at are set.
  NOTHING_TO_FLUSH — no live snapshot or empty graph — nothing to do; safe to clear.
  FAILED          — a recoverable error occurred; do NOT clear the snapshot.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

from asgiref.sync import sync_to_async

from tables.exceptions import (
    BulkSaveValidationError,
    ContentHashConflictError,
    GraphSaveVersionConflictError,
)
from tables.graph_collab.graph_state_service import (
    _KNOWN_LIST_KEYS,
    graph_state_service,
)
from tables.graph_collab.snapshot_normalize import inject_bulk_save_fields
from tables.serializers.graph_bulk_save_serializers import GraphBulkSaveInputSerializer
from tables.services.graph_bulk_save_service import GraphBulkSaveService
from utils.logger import logger


@dataclass(frozen=True)
class FlushOutcome:
    """Always returned by GraphFlushService.flush() — never raises.

    Check ``.status`` before accessing ``.result``:
      - SAVED          → ``.result`` is a :class:`FlushResult` with save data.
      - NOTHING_TO_FLUSH / FAILED → ``.result`` is None.

    When status is FAILED, ``failure_reason`` carries a short category string:
      - ``"validation_error"``      — serializer validation failed (persistent).
      - ``"bulk_save_validation"``  — BulkSaveValidationError from the service (persistent).
      - ``"db_error"``              — unexpected DB error (persistent).
      - ``"version_conflict"``      — concurrent REST save won; next tick retries (transient).
    """

    status: FlushStatus
    result: FlushResult | None = None
    failure_reason: str | None = None

    @property
    def saved(self) -> bool:
        return self.status is FlushStatus.SAVED

    @property
    def safe_to_clear(self) -> bool:
        """True when the snapshot can safely be cleared (persisted or nothing there)."""
        return self.status in (FlushStatus.SAVED, FlushStatus.NOTHING_TO_FLUSH)

    @property
    def persistent(self) -> bool:
        """True when FAILED and the error is not a transient version conflict."""
        return (
            self.status is FlushStatus.FAILED
            and self.failure_reason != "version_conflict"
        )


class FlushStatus(enum.Enum):
    SAVED = "saved"
    NOTHING_TO_FLUSH = "nothing_to_flush"
    FAILED = "failed"


@dataclass(frozen=True)
class FlushResult:
    """Payload embedded in FlushOutcome when status is SAVED."""

    new_save_version: int
    temp_id_map: dict[str, int]
    saved_at: str  # ISO-8601 UTC timestamp
    # The snapshot's deleted accumulator at the time of the flush, used by
    # apply_id_remap to perform a precise set-difference rather than a blanket clear.
    flushed_deleted: dict[str, list]


class _DbFlushResult(enum.Enum):
    SKIP = "skip"
    GRAPH_NOT_FOUND = "graph_not_found"
    VERSION_CONFLICT = "version_conflict"


def _do_db_flush(graph_id: int, snapshot: dict):
    """Synchronous DB work: validate snapshot and persist via GraphBulkSaveService.

    Returns ``(new_save_version: int, temp_id_map: dict)`` on success, or one of
    the module-level sentinels (possibly paired with a reason string) when the
    flush should be skipped:
      ``(_SKIP, reason)``       — persistent error (validation, BulkSave, DB error).
      ``_VERSION_CONFLICT``     — transient conflict; next tick will retry.
      ``_GRAPH_NOT_FOUND``      — graph row no longer exists in the DB.

    All expected failure modes are caught here and converted to logged
    warnings + the appropriate sentinel.  Only genuinely unexpected errors
    are allowed to propagate.
    """
    from tables.models import Graph

    try:
        graph = Graph.objects.get(pk=graph_id)
    except Graph.DoesNotExist:
        logger.warning(
            "GraphFlushService: graph {} not found during flush — skipping", graph_id
        )
        return _DbFlushResult.GRAPH_NOT_FOUND

    payload = inject_bulk_save_fields(snapshot, graph_id=graph_id)
    # Server is the authority on save_version — use the DB value so we never
    # self-conflict against a version we just wrote.
    payload["save_version"] = graph.save_version

    serializer = GraphBulkSaveInputSerializer(data=payload)
    if not serializer.is_valid():
        logger.warning(
            "GraphFlushService: flush validation failed for graph {}: {}",
            graph_id,
            serializer.errors,
        )
        return _DbFlushResult.SKIP, "validation_error"

    try:
        graph, temp_id_map = GraphBulkSaveService().save(
            graph, serializer.validated_data
        )
    except BulkSaveValidationError as exc:
        logger.warning(
            "GraphFlushService: BulkSaveValidationError for graph {}: {}",
            graph_id,
            exc.errors,
        )
        return _DbFlushResult.SKIP, "bulk_save_validation"
    except GraphSaveVersionConflictError as exc:
        logger.warning(
            "GraphFlushService: GraphSaveVersionConflictError for graph {} — "
            "a concurrent REST save won; next autosave tick will retry. detail: {}",
            graph_id,
            exc,
        )
        return _DbFlushResult.VERSION_CONFLICT
    except ContentHashConflictError as exc:
        logger.warning(
            "GraphFlushService: ContentHashConflictError for graph {} — "
            "a concurrent edit modified a node; next autosave tick will retry. detail: {}",
            graph_id,
            exc,
        )
        return _DbFlushResult.VERSION_CONFLICT

    graph.refresh_from_db(fields=["save_version"])
    return graph.save_version, temp_id_map


_async_do_db_flush = sync_to_async(_do_db_flush)


class GraphFlushService:
    """Flush the Redis live snapshot for one graph to the database.

    Intended to be called from autosave triggers (periodic task, last-leave,
    backstop).  Do NOT call this from inside the WebSocket consumer — that is
    the trigger layer's responsibility.

    Usage::

        outcome = await flush_service.flush(graph_id)
        if outcome.saved:
            # broadcast outcome.result.new_save_version + outcome.result.temp_id_map
        elif not outcome.safe_to_clear:
            # flush failed — do NOT clear the snapshot; log and retain it
    """

    async def flush(self, graph_id: int) -> FlushOutcome:
        """Flush the live snapshot for *graph_id* to the database.

        Always returns a :class:`FlushOutcome`.  Never raises from expected
        error conditions.

        Outcome statuses:
        - SAVED            — snapshot persisted; result carries save data.
        - NOTHING_TO_FLUSH — no live snapshot exists in Redis.
        - FAILED           — graph not found, validation failure, or version
                             conflict; snapshot is retained in Redis so users
                             do not lose work.
        """
        snapshot = await graph_state_service.get_snapshot(graph_id)
        if snapshot is None:
            logger.debug(
                "GraphFlushService: no live snapshot for graph {} — nothing to flush",
                graph_id,
            )
            return FlushOutcome(status=FlushStatus.NOTHING_TO_FLUSH)

        # Capture the deleted accumulator from the snapshot we are about to
        # persist so apply_id_remap can do a precise set-difference later.
        flushed_deleted: dict[str, list] = {
            key: list(ids) for key, ids in snapshot.get("deleted", {}).items()
        }

        # Build a mapping of temp_id → list_key from the snapshot BEFORE the
        # DB flush so apply_id_remap can identify the list_key of orphaned
        # entries. All list types are included: edges and conditional edges
        # carry their own temp_id (distinct from the start/end/source_temp_id
        # endpoint-reference fields on the same entry), and that own temp_id
        # must also be self-stamped and orphan-checked like node temp_ids.
        flushed_temp_id_to_list_key: dict[str, str] = {}
        for list_key in _KNOWN_LIST_KEYS:
            for entry in snapshot.get(list_key, []):
                if entry is None:
                    # Corrupted snapshot entry — skip; the serializer will reject
                    # the payload and the flush will return FAILED so the snapshot
                    # is retained for manual recovery.
                    logger.warning(
                        "GraphFlushService: None entry in {} for graph {} — "
                        "snapshot may be corrupted",
                        list_key,
                        graph_id,
                    )
                    continue
                tid = entry.get("temp_id")
                if tid is not None:
                    flushed_temp_id_to_list_key[str(tid)] = list_key

        db_result = await _async_do_db_flush(graph_id, snapshot)

        if db_result is _DbFlushResult.GRAPH_NOT_FOUND:
            # Graph no longer exists — clear the stale snapshot and treat as
            # nothing-to-flush (not a data-loss failure).
            await graph_state_service.clear(graph_id)
            logger.info(
                "GraphFlushService: cleared stale snapshot for deleted graph {}",
                graph_id,
            )
            return FlushOutcome(status=FlushStatus.NOTHING_TO_FLUSH)

        if db_result is _DbFlushResult.VERSION_CONFLICT:
            # Transient conflict — a concurrent REST save won; next tick retries.
            # No broadcast to clients; this self-corrects.
            logger.warning(
                "GraphFlushService: version conflict for graph {} — retrying next tick",
                graph_id,
            )
            return FlushOutcome(
                status=FlushStatus.FAILED, failure_reason="version_conflict"
            )

        if isinstance(db_result, tuple) and db_result[0] is _DbFlushResult.SKIP:
            # Persistent error (validation or BulkSave) — retain snapshot.
            _, reason = db_result
            logger.error(
                "GraphFlushService: flush FAILED ({}) for graph {} — snapshot retained for recovery",
                reason,
                graph_id,
            )
            return FlushOutcome(status=FlushStatus.FAILED, failure_reason=reason)

        new_save_version, temp_id_map = db_result
        await graph_state_service.apply_id_remap(
            graph_id,
            temp_id_map,
            new_save_version,
            flushed_deleted=flushed_deleted,
            flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
        )

        saved_at = datetime.now(tz=timezone.utc).isoformat()
        logger.info(
            "GraphFlushService: flushed graph {} → save_version={}, {} new nodes",
            graph_id,
            new_save_version,
            len(temp_id_map),
        )
        flush_result = FlushResult(
            new_save_version=new_save_version,
            temp_id_map=temp_id_map,
            saved_at=saved_at,
            flushed_deleted=flushed_deleted,
        )
        return FlushOutcome(status=FlushStatus.SAVED, result=flush_result)

    async def flush_if_dirty(self, graph_id: int) -> FlushOutcome:
        """Flush *graph_id* only when the snapshot has changed since the last flush.

        Captures the current revision under the per-graph lock, then releases the
        lock before the DB round-trip (never hold a lock across I/O).  On a
        successful save, ``mark_flushed`` is called with the *captured* revision —
        not the current one — so edits that arrived during the DB write are not
        silently dropped: ``is_dirty`` stays True and the next tick picks them up.

        Returns ``NOTHING_TO_FLUSH`` immediately when the snapshot is clean.
        """
        async with graph_state_service._get_lock(graph_id):
            if not graph_state_service.is_dirty(graph_id):
                return FlushOutcome(status=FlushStatus.NOTHING_TO_FLUSH)
            captured_revision = graph_state_service.current_revision(graph_id)
        # Lock released before the DB call.
        outcome = await self.flush(graph_id)
        if outcome.saved:
            graph_state_service.mark_flushed(graph_id, captured_revision)
        return outcome


flush_service = GraphFlushService()
