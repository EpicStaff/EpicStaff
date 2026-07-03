"""
Per-graph live snapshot service.

Keeps an authoritative **superset** JSON blob in Redis so late-joining editors
receive the current unsaved state, not the last DB-saved version, and so that
a future flush (Block 4) can send the snapshot directly through
GraphBulkSaveInputSerializer without additional transformation.

Snapshot shape (Django/superset form)
======================================
{
    "save_version": <int>,          # graph.save_version at seed time

    # All 13 node type lists (GraphSerializer READ shape + injected write ids):
    "crew_node_list":                 [...],
    "python_node_list":               [...],
    "file_extractor_node_list":       [...],
    "audio_transcription_node_list":  [...],
    "start_node_list":                [...],
    "end_node_list":                  [...],
    "subgraph_node_list":             [...],
    "decision_table_node_list":       [...],
    "graph_note_list":                [...],
    "webhook_trigger_node_list":      [...],
    "telegram_trigger_node_list":     [...],
    "schedule_trigger_node_list":     [...],
    "code_agent_node_list":           [...],
    "classification_decision_table_node_list": [...],

    # Edge lists:
    "edge_list":             [...],
    "conditional_edge_list": [...],

    # Deleted-entities accumulator (shape expected by DeletedEntitiesSerializer):
    "deleted": {
        "edge_ids":                       [],
        "conditional_edge_ids":           [],
        "crew_node_ids":                  [],
        "python_node_ids":                [],
        "file_extractor_node_ids":        [],
        "audio_transcription_node_ids":   [],
        "start_node_ids":                 [],
        "end_node_ids":                   [],
        "subgraph_node_ids":              [],
        "decision_table_node_ids":        [],
        "graph_note_ids":                 [],
        "webhook_trigger_node_ids":       [],
        "telegram_trigger_node_ids":      [],
        "schedule_trigger_node_ids":      [],
        "code_agent_node_ids":            [],
        "classification_decision_table_node_ids": [],
    },
}

Each node entry is the GraphSerializer READ output for that node plus any
injected write-only FK fields (see snapshot_normalize.inject_bulk_save_fields).
New nodes not yet persisted carry a "temp_id" string instead of a real "id".

Key:   graph:live:{graph_id}
Value: JSON-encoded superset snapshot
TTL:   GRAPH_LIVE_STATE_TTL_SECONDS (safety net; real cleanup is last-leave clear)

Concurrent apply_op calls for the same graph are serialised with a per-graph
asyncio.Lock so read-modify-write cycles never lose updates in the single worker.
"""

import asyncio
import json

from asgiref.sync import sync_to_async
from django.conf import settings

from tables.graph_collab.protocol import (
    ConnectionCreatedMessage,
    ConnectionDeletedMessage,
    ConnectionWaypointsUpdatedMessage,
    ConnectionsDeletedMessage,
    NodeCreatedMessage,
    NodeUpdatedMessage,
    NodesDeletedMessage,
)
from tables.graph_collab.op_normalize import normalize_op_entry
from tables.graph_collab.snapshot_normalize import inject_bulk_save_fields
from tables.services.redis_service import RedisService
from utils.logger import logger


def _redis_key(graph_id: int) -> str:
    return f"graph:live:{graph_id}"


def _tempids_key(graph_id: int) -> str:
    return f"graph:live:{graph_id}:tempids"


def _match_entry(entry: dict, id_value: int | None, temp_id: str | None) -> bool:
    """Return True when *entry* matches the provided id or temp_id reference.

    Matching rules (same discipline as BulkSaveEntityMixin):
    - If both caller id and entry id are non-null ints: compare by id.
    - Otherwise if both caller temp_id and entry temp_id are non-empty strings:
      compare by temp_id.
    - Otherwise: no match.
    """
    if id_value is not None and entry.get("id") is not None:
        return entry["id"] == id_value
    if temp_id is not None and entry.get("temp_id") is not None:
        return str(entry["temp_id"]) == str(temp_id)
    return False


def _upsert_entry(entries: list[dict], new_entry: dict) -> None:
    """Replace the matching entry in *entries* in-place, or append if not found.

    Uses the same matching logic as _match_entry.  Mutates *entries*.
    """
    entry_id = new_entry.get("id")
    entry_temp_id = new_entry.get("temp_id")
    for index, existing in enumerate(entries):
        if _match_entry(existing, entry_id, entry_temp_id):
            entries[index] = new_entry
            return
    entries.append(new_entry)


_EDGE_ENDPOINT_TEMP_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "edge_list": (("start_temp_id", "start_node_id"), ("end_temp_id", "end_node_id")),
    "conditional_edge_list": (("source_temp_id", "source_node_id"),),
}


def _resolve_edge_endpoints(
    entry: dict, list_key: str, resolved_temp_ids: dict[str, int]
) -> dict:
    """Rewrite already-resolved endpoint temp_id refs on an edge *entry*.

    Only touches endpoint reference fields (start_temp_id/end_temp_id for
    edge_list, source_temp_id for conditional_edge_list) — never the edge's
    own ``temp_id``. A ref is rewritten only when its value is present in
    *resolved_temp_ids*; otherwise it is left untouched so the normal
    flush-time resolution (via the referenced node's own temp_id) still
    applies.
    """
    field_pairs = _EDGE_ENDPOINT_TEMP_FIELDS.get(list_key)
    if not field_pairs:
        return entry
    for temp_field, real_field in field_pairs:
        temp_value = entry.get(temp_field)
        if temp_value is None:
            continue
        real_id = resolved_temp_ids.get(str(temp_value))
        if real_id is not None:
            entry[real_field] = real_id
            entry.pop(temp_field, None)
    return entry


# Maps list_key to the corresponding deleted-accumulator key. Covers every
# list type: node lists use the <type>_node_ids pattern; edge lists use
# edge_ids / conditional_edge_ids.
_LIST_KEY_TO_DELETE_KEY: dict[str, str] = {
    "crew_node_list": "crew_node_ids",
    "python_node_list": "python_node_ids",
    "file_extractor_node_list": "file_extractor_node_ids",
    "audio_transcription_node_list": "audio_transcription_node_ids",
    "start_node_list": "start_node_ids",
    "end_node_list": "end_node_ids",
    "subgraph_node_list": "subgraph_node_ids",
    "decision_table_node_list": "decision_table_node_ids",
    "graph_note_list": "graph_note_ids",
    "webhook_trigger_node_list": "webhook_trigger_node_ids",
    "telegram_trigger_node_list": "telegram_trigger_node_ids",
    "schedule_trigger_node_list": "schedule_trigger_node_ids",
    "code_agent_node_list": "code_agent_node_ids",
    "classification_decision_table_node_list": "classification_decision_table_node_ids",
    "edge_list": "edge_ids",
    "conditional_edge_list": "conditional_edge_ids",
}

_KNOWN_LIST_KEYS: frozenset[str] = frozenset(_LIST_KEY_TO_DELETE_KEY.keys())

_EMPTY_DELETED: dict[str, list] = {
    "edge_ids": [],
    "conditional_edge_ids": [],
    "crew_node_ids": [],
    "python_node_ids": [],
    "file_extractor_node_ids": [],
    "audio_transcription_node_ids": [],
    "start_node_ids": [],
    "end_node_ids": [],
    "subgraph_node_ids": [],
    "decision_table_node_ids": [],
    "graph_note_ids": [],
    "webhook_trigger_node_ids": [],
    "telegram_trigger_node_ids": [],
    "schedule_trigger_node_ids": [],
    "code_agent_node_ids": [],
    "classification_decision_table_node_ids": [],
}


class GraphLiveStateService:
    """Maintains per-graph authoritative live snapshots in Redis.

    The stored snapshot is in Django/superset form (see module docstring).
    Seeding from the DB is done via seed_from_db() which uses GraphSerializer
    plus inject_bulk_save_fields().  apply_op() mutates the snapshot in response
    to inbound WebSocket op messages.
    """

    def __init__(self) -> None:
        # Lazily-created per-graph asyncio locks to serialise apply_op.
        self._locks: dict[int, asyncio.Lock] = {}
        # Monotonically incrementing counter bumped on every mutating apply_op.
        self._revision: dict[int, int] = {}
        # Revision value at the time of the last successful flush.
        self._flushed_revision: dict[int, int] = {}

    def _get_lock(self, graph_id: int) -> asyncio.Lock:
        if graph_id not in self._locks:
            self._locks[graph_id] = asyncio.Lock()
        return self._locks[graph_id]

    def current_revision(self, graph_id: int) -> int:
        """Return the current revision counter for *graph_id* (0 if unseen)."""
        return self._revision.get(graph_id, 0)

    def is_dirty(self, graph_id: int) -> bool:
        """Return True when the snapshot has unsaved changes since the last flush."""
        return self._revision.get(graph_id, 0) != self._flushed_revision.get(
            graph_id, 0
        )

    def mark_flushed(self, graph_id: int, revision: int) -> None:
        """Record that *revision* was successfully persisted to the DB.

        Always stores the captured revision, never the current one — this is
        intentional: edits arriving during the DB round-trip bump the current
        revision beyond *revision*, so ``is_dirty`` stays True and the next
        autosave tick will pick them up.
        """
        self._flushed_revision[graph_id] = revision

    @property
    def _redis(self):
        """Resolve the async Redis client lazily so tests can patch it."""
        return RedisService().async_redis_client

    async def seed(self, graph_id: int, flow: dict) -> None:
        """Store *flow* as the live snapshot for *graph_id* with a safety TTL."""
        key = _redis_key(graph_id)
        ttl = getattr(settings, "GRAPH_LIVE_STATE_TTL_SECONDS", 86400)
        await self._redis.set(key, json.dumps(flow), ex=ttl)
        logger.debug("Seeded live state for graph {}", graph_id)

    async def seed_from_db(self, graph_id: int) -> bool:
        """Load the graph from the DB, serialise it, inject bulk-save fields, and seed.

        Uses GraphSerializer (the canonical READ serializer) so the snapshot
        always matches what the API returns.  inject_bulk_save_fields() adds
        the write-only FK ids needed for a future flush.

        Returns True when seeding succeeded, False when the graph was not found
        (deleted between handshake and seed).  Callers should close the
        connection cleanly when False is returned.

        The DB load happens outside the per-graph lock (expensive, idempotent),
        but the "is it already seeded?" check and the seed write are done
        atomically under the lock.  Without this, two overlapping connects for
        the same never-yet-seeded graph can both observe an absent snapshot,
        both load the (near-empty) DB state, and the one that acquires the
        lock last unconditionally overwrites whatever ops the other connection
        already applied via apply_op — stomping live nodes/edges and resetting
        the revision counter.
        """
        snapshot = await _load_graph_snapshot(graph_id)
        if snapshot is None:
            return False
        async with self._get_lock(graph_id):
            # Re-check under the lock: a concurrent connect may have already
            # seeded this graph (and clients may have applied ops on top).
            # Overwriting now would stomp that live state and orphan edges
            # referencing stomped nodes.
            if await self.get_snapshot(graph_id) is not None:
                logger.debug(
                    "seed_from_db: graph {} already seeded concurrently — skipping",
                    graph_id,
                )
                return True
            await self.seed(graph_id, snapshot)
            # Fresh seed from DB — treat as not dirty so the next autosave tick
            # does not immediately write back an unchanged snapshot.
            self._revision[graph_id] = 0
            self._flushed_revision[graph_id] = 0
        logger.debug("Seeded graph {} from DB", graph_id)
        return True

    async def get_snapshot(self, graph_id: int) -> dict | None:
        """Return the live snapshot for *graph_id*, or None if absent."""
        raw = await self._redis.get(_redis_key(graph_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def clear(self, graph_id: int) -> None:
        """Delete the live snapshot for *graph_id* (called when last editor leaves)."""
        await self._redis.delete(_redis_key(graph_id))
        await self._redis.delete(_tempids_key(graph_id))
        logger.debug("Cleared live state for graph {}", graph_id)
        # Release the lock entry and revision counters — recreated on next use.
        self._locks.pop(graph_id, None)
        self._revision.pop(graph_id, None)
        self._flushed_revision.pop(graph_id, None)

    async def record_resolved_temp_ids(
        self, graph_id: int, mapping: dict[str, int]
    ) -> None:
        """Merge *mapping* into the retained temp_id -> real_id map for *graph_id*.

        The retained map lets a late-arriving op that references an already
        -remapped temp_id (the node was flushed and no longer carries that
        temp_id in the live snapshot) resolve to the real id at apply_op time
        instead of failing bulk-save validation on the next flush.

        No-op when *mapping* is empty.
        """
        if not mapping:
            return
        resolved = await self.get_resolved_temp_ids(graph_id)
        resolved.update(mapping)
        ttl = getattr(settings, "GRAPH_LIVE_STATE_TTL_SECONDS", 86400)
        await self._redis.set(_tempids_key(graph_id), json.dumps(resolved), ex=ttl)

    async def get_resolved_temp_ids(self, graph_id: int) -> dict[str, int]:
        """Return the retained temp_id -> real_id map for *graph_id* (or {})."""
        raw = await self._redis.get(_tempids_key(graph_id))
        if raw is None:
            return {}
        return json.loads(raw)

    async def apply_id_remap(
        self,
        graph_id: int,
        temp_id_map: dict[str, int],
        new_save_version: int,
        *,
        flushed_deleted: dict[str, list] | None = None,
        flushed_temp_id_to_list_key: dict[str, str] | None = None,
    ) -> None:
        """Rewrite temp_id references in the stored snapshot to real DB ids.

        Called immediately after a successful flush so that subsequent flushes
        treat the newly-created nodes as updates (they carry real ``id`` fields)
        rather than re-creating them.

        Under the per-graph lock:
        - For every node entry whose ``temp_id`` key is present in *temp_id_map*,
          set ``id = temp_id_map[temp_id]`` and remove the ``temp_id`` field.
        - For every edge / conditional edge entry, rewrite ``start_temp_id``,
          ``end_temp_id``, or ``source_temp_id`` → the matching ``*_node_id``
          integer using *temp_id_map*, then remove the temp field.
        - Bump ``save_version`` to *new_save_version*.
        - Merge *temp_id_map* into the retained temp_id -> real_id map (see
          record_resolved_temp_ids) so a later op referencing one of these
          temp_ids as an edge endpoint can still resolve to the real id.
        - Precise deleted-accumulator reconciliation (FIX 2): remove from the
          live accumulator ONLY the ids that were present in *flushed_deleted*
          (i.e. the exact set that was just persisted).  ids accumulated after
          the flush read-point are preserved for the next flush.
        - Orphan detection (FIX 3): for each temp_id that was in the flushed
          snapshot but is no longer present in the live snapshot, append the
          mapped real id to the live accumulator so the next flush deletes it.
          Requires *flushed_temp_id_to_list_key* to determine which list the
          orphaned node belonged to.
        - Re-store with TTL.

        No-op if no snapshot exists for *graph_id*.

        *flushed_deleted* and *flushed_temp_id_to_list_key* default to None for
        backwards compatibility in tests that call apply_id_remap directly.
        When None, behaviour degrades to the old blanket-clear and skips orphan
        detection (safe for unit-test callers that don't exercise concurrency).
        """
        async with self._get_lock(graph_id):
            snapshot = await self.get_snapshot(graph_id)
            if snapshot is None:
                logger.debug(
                    "apply_id_remap: no snapshot for graph {} — skipping", graph_id
                )
                return

            live_deleted: dict = snapshot.setdefault("deleted", _make_empty_deleted())

            # Rewrite node entries in every node list.
            # Simultaneously collect the set of temp_ids still present in the
            # LIVE snapshot so we can detect orphans
            live_temp_ids: set[str] = set()
            for list_key in _KNOWN_LIST_KEYS:
                entries: list[dict] = snapshot.get(list_key, [])
                for entry in entries:
                    tid = entry.get("temp_id")
                    if tid is not None:
                        live_temp_ids.add(str(tid))
                        real_id = temp_id_map.get(str(tid))
                        if real_id is not None:
                            entry["id"] = real_id
                            entry.pop("temp_id", None)

            # Rewrite edge references.
            for edge in snapshot.get("edge_list", []):
                start_temp = edge.get("start_temp_id")
                if start_temp is not None:
                    real_id = temp_id_map.get(str(start_temp))
                    if real_id is not None:
                        edge["start_node_id"] = real_id
                        edge.pop("start_temp_id", None)

                end_temp = edge.get("end_temp_id")
                if end_temp is not None:
                    real_id = temp_id_map.get(str(end_temp))
                    if real_id is not None:
                        edge["end_node_id"] = real_id
                        edge.pop("end_temp_id", None)

            # Rewrite conditional edge references.
            for cond_edge in snapshot.get("conditional_edge_list", []):
                source_temp = cond_edge.get("source_temp_id")
                if source_temp is not None:
                    real_id = temp_id_map.get(str(source_temp))
                    if real_id is not None:
                        cond_edge["source_node_id"] = real_id
                        cond_edge.pop("source_temp_id", None)

            # Rewrite routing references inside decision-table entries.
            # Their default/error/per-group next-node refs use the same
            # temp-vs-real duality as edge endpoints; without this rewrite a
            # flushed routing target keeps a *_temp_id that no longer exists in
            # any node list and every subsequent flush fails validation.
            def _remap_ref(entry: dict, temp_key: str, id_key: str) -> None:
                temp_val = entry.get(temp_key)
                if temp_val is None:
                    return
                real = temp_id_map.get(str(temp_val))
                if real is not None:
                    entry[id_key] = real
                    entry.pop(temp_key, None)

            for list_key in (
                "decision_table_node_list",
                "classification_decision_table_node_list",
            ):
                for table_entry in snapshot.get(list_key, []):
                    if table_entry is None:
                        continue
                    _remap_ref(
                        table_entry, "default_next_node_temp_id", "default_next_node_id"
                    )
                    _remap_ref(
                        table_entry, "next_error_node_temp_id", "next_error_node_id"
                    )
                    for group in table_entry.get("condition_groups") or []:
                        if isinstance(group, dict):
                            _remap_ref(group, "next_node_temp_id", "next_node_id")

            snapshot["save_version"] = new_save_version

            # Remove from the live accumulator only the ids that were in the
            # flushed snapshot at flush-read time — ids accumulated after that
            # point (concurrent apply_op deletes) are preserved.
            if flushed_deleted is not None:
                for delete_key, persisted_ids in flushed_deleted.items():
                    if not persisted_ids:
                        continue
                    live_ids: list = live_deleted.get(delete_key, [])
                    persisted_set = set(persisted_ids)
                    live_deleted[delete_key] = [
                        id_ for id_ in live_ids if id_ not in persisted_set
                    ]

            else:
                # Fallback for callers that do not supply flushed_deleted
                # (e.g. legacy test call-sites): blanket-clear as before.
                snapshot["deleted"] = _make_empty_deleted()
                live_deleted = snapshot["deleted"]

            # Orphan node detection.
            # A node with temp_id T was in the flushed snapshot (and therefore
            # created in the DB with real id R), but T is no longer present in
            # the live snapshot (it was concurrently deleted via apply_op).
            # The DB row now exists but the live snapshot has no record of it,
            # so a future flush will never delete it unless we enqueue R here.
            #
            # *flushed_temp_id_to_list_key* maps each temp_id that existed in
            # the flushed snapshot to its list_key, allowing us to determine
            # the correct accumulator key without scanning the live snapshot.
            if temp_id_map and flushed_temp_id_to_list_key:
                orphaned_temp_ids: set[str] = (
                    frozenset(temp_id_map.keys()) - live_temp_ids
                )
                for tid in orphaned_temp_ids:
                    real_id = temp_id_map[tid]
                    list_key = flushed_temp_id_to_list_key.get(tid)
                    if list_key is None:
                        # Shouldn't happen if caller built the map correctly.
                        logger.warning(
                            "apply_id_remap: orphaned temp_id {} not in "
                            "flushed_temp_id_to_list_key for graph {}",
                            tid,
                            graph_id,
                        )
                        continue
                    delete_key = _LIST_KEY_TO_DELETE_KEY.get(list_key)
                    if delete_key:
                        acc: list = live_deleted.setdefault(delete_key, [])
                        if real_id not in acc:
                            acc.append(real_id)
                        logger.debug(
                            "apply_id_remap: enqueued orphan real_id {} "
                            "(temp_id {}) under {} for graph {}",
                            real_id,
                            tid,
                            delete_key,
                            graph_id,
                        )

            await self.seed(graph_id, snapshot)
            await self.record_resolved_temp_ids(graph_id, temp_id_map)
            logger.debug(
                "apply_id_remap: remapped {} temp ids for graph {}, save_version={}",
                len(temp_id_map),
                graph_id,
                new_save_version,
            )

    async def apply_op(self, graph_id: int, message) -> None:
        """Mutate the stored superset snapshot according to *message*.

        If no snapshot exists yet (race between seed and op), the op is dropped
        silently — the real state will arrive via seed shortly after.

        All mutation for a given graph_id is serialised with an asyncio.Lock to
        prevent lost-update races in the single async worker.

        Op semantics:
        - NodeCreatedMessage / NodeUpdatedMessage: upsert by id (when both are
          non-null ints) or temp_id (string) in the list named by message.list_key.
          If the upserted entry carries a real integer id that is currently in
          the deleted accumulator (delete-then-readd scenario), that id is removed
          from the accumulator so a later flush does not delete the re-added node.
        - NodesDeletedMessage: remove each ref from its list_key; when a removed
          entry had a real integer id, append it to the snapshot's deleted
          accumulator under the corresponding <type>_node_ids key.
        - ConnectionCreatedMessage: upsert into edge_list or conditional_edge_list
          (determined by message.list_key).
        - ConnectionDeletedMessage: remove single entry from message.list_key.
        - ConnectionsDeletedMessage: remove each ref from its list_key.
        - ConnectionWaypointsUpdatedMessage: mutate the edge entry's metadata
          (or waypoints field directly).

        Unknown list_key values are rejected with a warning and treated as a
        no-op — they must not mutate the snapshot.
        """
        # TODO implement a Strategy pattern instead of long if-else
        async with self._get_lock(graph_id):
            snapshot = await self.get_snapshot(graph_id)
            if snapshot is None:
                logger.debug(
                    "apply_op: no snapshot for graph {} yet — dropping op {}",
                    graph_id,
                    getattr(message, "type", "?"),
                )
                return

            deleted: dict = snapshot.setdefault("deleted", _make_empty_deleted())

            if isinstance(message, NodeCreatedMessage | NodeUpdatedMessage):
                list_key = message.list_key
                if list_key not in _KNOWN_LIST_KEYS:
                    logger.warning(
                        "Ignoring op with unknown list_key {} on graph {}",
                        list_key,
                        graph_id,
                    )
                    return
                entries: list[dict] = snapshot.setdefault(list_key, [])
                new_entry = normalize_op_entry(list_key, message.node)
                _upsert_entry(entries, new_entry)

                # if this node has a real id that was previously deleted,
                # remove it from the accumulator — the node is alive again.
                entry_id = new_entry.get("id")
                if entry_id is not None:
                    delete_key = _LIST_KEY_TO_DELETE_KEY.get(list_key)
                    if delete_key:
                        accumulator: list = deleted.get(delete_key, [])
                        if entry_id in accumulator:
                            accumulator.remove(entry_id)

            elif isinstance(message, NodesDeletedMessage):
                for ref in message.refs:
                    list_key = ref.list_key
                    if list_key not in _KNOWN_LIST_KEYS:
                        logger.warning(
                            "Ignoring delete ref with unknown list_key {} on graph {}",
                            list_key,
                            graph_id,
                        )
                        continue
                    entries = snapshot.setdefault(list_key, [])
                    surviving = []
                    for entry in entries:
                        if _match_entry(entry, ref.id, ref.temp_id):
                            # Accumulate real ids for the eventual flush.
                            if ref.id is not None:
                                delete_key = _LIST_KEY_TO_DELETE_KEY.get(list_key)
                                if delete_key:
                                    deleted.setdefault(delete_key, []).append(ref.id)
                        else:
                            surviving.append(entry)
                    snapshot[list_key] = surviving

            elif isinstance(message, ConnectionCreatedMessage):
                list_key = message.list_key
                if list_key not in _KNOWN_LIST_KEYS:
                    logger.warning(
                        "Ignoring op with unknown list_key {} on graph {}",
                        list_key,
                        graph_id,
                    )
                    return
                entries = snapshot.setdefault(list_key, [])
                new_connection = normalize_op_entry(list_key, message.connection)

                resolved_temp_ids = await self.get_resolved_temp_ids(graph_id)
                new_connection = _resolve_edge_endpoints(
                    new_connection, list_key, resolved_temp_ids
                )
                _upsert_entry(entries, new_connection)
                # re-added connection — remove from deleted accumulator.
                connection_id = new_connection.get("id")
                if connection_id is not None:
                    delete_key = _LIST_KEY_TO_DELETE_KEY.get(list_key)
                    if delete_key:
                        accumulator = deleted.get(delete_key, [])
                        if connection_id in accumulator:
                            accumulator.remove(connection_id)

            elif isinstance(message, ConnectionDeletedMessage):
                list_key = message.list_key
                if list_key not in _KNOWN_LIST_KEYS:
                    logger.warning(
                        "Ignoring op with unknown list_key {} on graph {}",
                        list_key,
                        graph_id,
                    )
                    return
                entries = snapshot.setdefault(list_key, [])
                surviving = []
                for entry in entries:
                    if _match_entry(entry, message.connection_id, message.temp_id):
                        if message.connection_id is not None:
                            delete_key = _LIST_KEY_TO_DELETE_KEY.get(list_key)
                            if delete_key:
                                deleted.setdefault(delete_key, []).append(
                                    message.connection_id
                                )
                    else:
                        surviving.append(entry)
                snapshot[list_key] = surviving

            elif isinstance(message, ConnectionsDeletedMessage):
                for ref in message.refs:
                    list_key = ref.list_key
                    if list_key not in _KNOWN_LIST_KEYS:
                        logger.warning(
                            "Ignoring delete ref with unknown list_key {} on graph {}",
                            list_key,
                            graph_id,
                        )
                        continue
                    entries = snapshot.setdefault(list_key, [])
                    surviving = []
                    for entry in entries:
                        if _match_entry(entry, ref.id, ref.temp_id):
                            if ref.id is not None:
                                delete_key = _LIST_KEY_TO_DELETE_KEY.get(list_key)
                                if delete_key:
                                    deleted.setdefault(delete_key, []).append(ref.id)
                        else:
                            surviving.append(entry)
                    snapshot[list_key] = surviving

            elif isinstance(message, ConnectionWaypointsUpdatedMessage):
                list_key = message.list_key
                if list_key not in _KNOWN_LIST_KEYS:
                    logger.warning(
                        "Ignoring op with unknown list_key {} on graph {}",
                        list_key,
                        graph_id,
                    )
                    return
                entries = snapshot.setdefault(list_key, [])
                for entry in entries:
                    if _match_entry(
                        entry,
                        message.connection_id
                        if isinstance(message.connection_id, int)
                        else None,
                        str(message.connection_id)
                        if not isinstance(message.connection_id, int)
                        else None,
                    ):
                        entry["waypoints"] = message.waypoints
                        break

            await self.seed(graph_id, snapshot)
            self._revision[graph_id] = self._revision.get(graph_id, 0) + 1


def _make_empty_deleted() -> dict:
    """Return a fresh deleted accumulator with all expected keys."""
    return {key: [] for key in _EMPTY_DELETED}


@sync_to_async
def _load_graph_snapshot(graph_id: int) -> dict | None:
    """Synchronous DB load wrapped for async use.

    Fetches the Graph ORM object, serialises it with GraphSerializer, then
    injects bulk-save fields.  Runs in a thread via sync_to_async.

    Returns None when the graph no longer exists (deleted between handshake
    and seed).  Callers must handle the None case.
    """
    from tables.models import Graph
    from tables.serializers.model_serializers.graph_serializers import GraphSerializer

    try:
        graph = Graph.objects.get(pk=graph_id)
    except Graph.DoesNotExist:
        logger.warning("Graph {} not found when seeding live state", graph_id)
        return None

    data = GraphSerializer(graph).data
    # DRF ReturnDict is not plain dict — convert before injection/storage.
    snapshot = dict(data)
    snapshot = inject_bulk_save_fields(snapshot, graph_id=graph_id)
    snapshot.setdefault("deleted", _make_empty_deleted())
    return snapshot


graph_state_service = GraphLiveStateService()
