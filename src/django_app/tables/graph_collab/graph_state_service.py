import asyncio
import json
import copy
from dataclasses import dataclass
from enum import Enum

from asgiref.sync import sync_to_async
from django.conf import settings

from tables.graph_collab.entry_merge import find_mismatched_keys, merge_entry
from tables.graph_collab.protocol import (
    ConnectionCreatedMessage,
    ConnectionDeletedMessage,
    ConnectionWaypointsUpdatedMessage,
    ConnectionsDeletedMessage,
    NodeCreatedMessage,
    NodeUpdatedMessage,
    NodesDeletedMessage,
)

from tables.graph_collab.snapshot_normalize import inject_bulk_save_fields
from tables.graph_collab.constants import (
    _SINGLETON_LIST_KEYS,
    _EDGE_ENDPOINT_TEMP_FIELDS,
    _ALL_LIST_KEYS,
    _LIST_KEY_TO_DELETE_KEY,
    _EDGE_NODE_REF_FIELDS,
    _DECISION_TABLE_LIST_KEYS,
    PRIVILEGED_NESTED_FIELDS,
)
from tables.services.redis_service import RedisService
from utils.logger import logger


class OpStatus(str, Enum):
    APPLIED = "applied"
    REJECTED = "rejected"


@dataclass(frozen=True)
class OpResult:
    """Outcome of a single apply_op call."""

    status: OpStatus
    reason: str | None = None
    relay: bool = True
    details: dict | None = None


APPLIED_OK = OpResult(OpStatus.APPLIED)


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


def _collapse_singleton_entry(
    entries: list[dict], new_entry: dict, list_key: str
) -> None:
    """
    Collapse *entries* to exactly one entry for an at-most-one-per-graph
    list (start_node_list / end_node_list — see _SINGLETON_LIST_KEYS).
    """
    existing_id = entries[0].get("id") if entries else None
    new_id = new_entry.get("id")

    if existing_id is not None and new_id is None:
        new_entry["id"] = existing_id
        new_entry.pop("temp_id", None)
    elif existing_id is not None and new_id is not None and existing_id != new_id:
        logger.warning(
            "Singleton list {} has two entries with different real ids "
            "({} vs {}) — keeping the new entry",
            list_key,
            existing_id,
            new_id,
        )

    entries[:] = [new_entry]


def _resolve_edge_endpoints(
    entry: dict, list_key: str, resolved_temp_ids: dict[str, int]
) -> dict:
    """Rewrite already-resolved endpoint temp_id refs on an edge *entry*."""
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


def _pin_privileged_fields(
    existing: dict | None, incoming: dict, list_key: str, is_superadmin: bool
) -> list[str]:
    """Force superadmin-only nested fields in *incoming* back to their
    currently-stored, authorized value for non-superadmins. Mutates
    *incoming* in place. Returns the names of fields that were overwritten
    because they differed from the authorized value.

    A resend of the current, unchanged value is intentionally NOT logged —
    resize / auto-arrange / reconnect-resync legitimately resend the current
    value unchanged on the legacy upsert path, so logging those would be
    pure noise at the call sites that consume this function's return value.

    When *incoming* carries the nested object but omits the field entirely,
    the authorized value is inserted (not reported) — merge_entry
    whole-key-replaces the nested object, so an overlay like
    {"path": "x"} would otherwise silently drop the existing config.
    """
    if is_superadmin:
        return []

    nested_fields = PRIVILEGED_NESTED_FIELDS.get(list_key)
    if not nested_fields:
        return []

    pinned: list[str] = []
    for nested_key, field_names in nested_fields.items():
        if nested_key not in incoming:
            continue

        nested_incoming = incoming[nested_key]
        if not isinstance(nested_incoming, dict):
            # e.g. webhook_trigger: None — no nested object is being written,
            # so there is nothing to pin.
            continue

        nested_existing = (existing or {}).get(nested_key) or {}

        for field_name in field_names:
            authorized_value = (
                nested_existing.get(field_name) if existing is not None else None
            )
            if field_name in nested_incoming:
                if nested_incoming[field_name] != authorized_value:
                    nested_incoming[field_name] = authorized_value
                    pinned.append(field_name)
            else:
                nested_incoming[field_name] = authorized_value

    return pinned


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
        """Load the graph from the DB, serialise it, inject bulk-save fields, and seed."""
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

    async def reset_from_db(self, graph_id: int) -> dict | None:
        """Clear the live snapshot and immediately reseed it from the DB"""
        await self.clear(graph_id)
        seeded = await self.seed_from_db(graph_id)
        if not seeded:
            return None
        return await self.get_snapshot(graph_id)

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

    async def prune_resolved_temp_ids(self, graph_id: int, dead_ids: set[int]) -> None:
        """Drop every entry of the retained temp_id -> real_id map whose real
        id is in *dead_ids* (a node/edge flushed as a deletion).

        This is a targeted prune, not a clear-on-success: record_resolved_temp_ids's
        whole purpose (see its docstring) is letting a late-arriving op that
        references an already-remapped temp_id resolve to the real id even
        after the node has been flushed out of the live snapshot. Clearing the
        map on every successful flush would destroy that for every temp_id
        that is still alive — so this only removes the entries that point at
        pks which no longer exist, filtering by VALUE, never by key. Do not
        "simplify" this into a blanket clear.

        No-op when *dead_ids* is empty.
        """
        if not dead_ids:
            return
        resolved = await self.get_resolved_temp_ids(graph_id)
        filtered = {
            temp_id: real_id
            for temp_id, real_id in resolved.items()
            if real_id not in dead_ids
        }
        if len(filtered) == len(resolved):
            # Nothing was actually pruned — skip the pointless Redis write
            # and TTL refresh.
            return
        ttl = getattr(settings, "GRAPH_LIVE_STATE_TTL_SECONDS", 86400)
        await self._redis.set(_tempids_key(graph_id), json.dumps(filtered), ex=ttl)

    async def apply_id_remap(
        self,
        graph_id: int,
        temp_id_map: dict[str, int],
        new_save_version: int,
        *,
        flushed_deleted: dict[str, list],
        flushed_temp_id_to_list_key: dict[str, str] | None = None,
    ) -> None:
        """Rewrite temp_id references in the stored snapshot to real DB ids.

        Called immediately after a successful flush so that subsequent flushes
        treat the newly-created nodes as updates (they carry real ``id`` fields)
        rather than re-creating them.
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
            for list_key in _ALL_LIST_KEYS:
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

            for list_key in _DECISION_TABLE_LIST_KEYS:
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
            # point (concurrent apply_op delete) must not be wiped, so this is
            # a precise set-difference, never a blanket clear.
            for delete_key, persisted_ids in flushed_deleted.items():
                if not persisted_ids:
                    continue
                live_ids: list = live_deleted.get(delete_key, [])
                persisted_set = set(persisted_ids)
                live_deleted[delete_key] = [
                    id_ for id_ in live_ids if id_ not in persisted_set
                ]

            # Invalidate the retained temp_id -> real_id map for every pk that
            # was just permanently hard-deleted by this flush. Without this,
            # a stale entry like {U: 42} survives after node 42 is deleted, and
            # a later op re-creating temp_id U (FE undo/redo replaying a stale
            # copy) resolves to the now-dead pk 42 instead of being treated as
            # a genuine create — the exact bug this fix targets.
            dead_ids: set[int] = {
                dead_id for ids in flushed_deleted.values() for dead_id in ids
            }
            await self.prune_resolved_temp_ids(graph_id, dead_ids)

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

            await _refresh_flushed_content_hashes(snapshot)

            await self.seed(graph_id, snapshot)
            await self.record_resolved_temp_ids(graph_id, temp_id_map)
            logger.debug(
                "apply_id_remap: remapped {} temp ids for graph {}, save_version={}",
                len(temp_id_map),
                graph_id,
                new_save_version,
            )

    async def apply_scheduler_deactivation(
        self,
        graph_id: int,
        node_id: int,
        list_key: str = "schedule_trigger_node_list",
    ) -> bool:
        """Mirror a scheduler-driven ``is_active=False`` / ``next_run_date_time=None``
        write into the live snapshot, scoped to the single touched node.

        The scheduler (`ScheduleTriggerService`) writes directly to the DB via
        a plain ``.save()``, bypassing the content_hash CAS channel collab
        autosave relies on. ``is_active`` is part of the node's content_hash,
        so an unmirrored write shifts the DB row's hash out from under any
        live snapshot, and the next autosave flush hits a real
        ``ContentHashConflictError`` — wedging the whole graph's autosave in
        an infinite poison-retry.

        This method only touches the snapshot when a live collaborative
        session actually exists for *graph_id* — the common case (nobody
        connected) is untouched, DB stays sole authority. It never bumps the
        revision/dirty counters: the DB is already correct, forcing a flush
        here would be redundant and could race the next real edit.

        Idempotent by design — safe to call once per connected client for the
        same deactivation event. Returns True if the snapshot was mutated,
        False otherwise (no live session, node absent, or already inactive).

        Cross-process safety note: this relies on ``self._get_lock(graph_id)``
        serialising against concurrent ``apply_op``/``apply_id_remap`` calls
        in THIS asyncio event loop. It assumes the single-ASGI-worker
        deployment already documented for the rest of this service — a
        second worker process would have its own unshared lock instance.
        """
        async with self._get_lock(graph_id):
            snapshot = await self.get_snapshot(graph_id)
            if snapshot is None:
                logger.debug(
                    "apply_scheduler_deactivation: no live snapshot for graph "
                    "{} — skipping",
                    graph_id,
                )
                return False

            entries: list[dict] = snapshot.get(list_key, [])
            entry = next((e for e in entries if e.get("id") == node_id), None)
            if entry is None:
                logger.debug(
                    "apply_scheduler_deactivation: node {} not found in {} "
                    "for graph {} — skipping",
                    node_id,
                    list_key,
                    graph_id,
                )
                return False

            if entry.get("is_active") is False:
                logger.debug(
                    "apply_scheduler_deactivation: node {} already inactive "
                    "in live snapshot for graph {} — skipping",
                    node_id,
                    graph_id,
                )
                return False

            entry["is_active"] = False
            entry["next_run_date_time"] = None
            if "content_hash" in entry:
                refreshed_hash = await _refresh_schedule_node_content_hash(node_id)
                if refreshed_hash is not None:
                    entry["content_hash"] = refreshed_hash

            await self.seed(graph_id, snapshot)
            logger.debug(
                "apply_scheduler_deactivation: node {} deactivated in live "
                "snapshot for graph {}",
                node_id,
                graph_id,
            )
            return True

    async def _apply_node_upsert(
        self,
        snapshot: dict,
        deleted: dict,
        message,
        graph_id: int,
        is_superadmin: bool = False,
    ) -> OpResult | None:
        """Handle NodeCreatedMessage and legacy NodeUpdatedMessage (changed_fields
        is None) — wholesale-replace upsert semantics: normalize_op_entry,
        singleton collapse or _upsert_entry (append-on-miss kept),
        deleted-accumulator resurrect kept.

        Returns None for an unknown list_key (mirrors the old bare `return` —
        apply_op's caller treats a None result as "relay, but nothing changed").

        NOTE: this legacy no-changed_fields path is still very much in use.
        Current callers include: note-node
        edit, node resize, auto-arrange (fires once per node — a full-upsert
        storm), start-node initial-state edit, broadcastFlowDiff's
        updated-nodes loop (reconnect-resync + Decision→Classification
        conversion), decision/classification table routing broadcast, and
        the python-node panel manual Save.
        """
        # Resolve a bare temp_id to its real id BEFORE the stale-id-recreate
        # guard below runs on message.node["id"] — this is what lets that
        # guard correctly reject/resurrect creates referenced by temp_id,
        # not just by real id.
        temp_id = message.node.get("temp_id")
        if message.node.get("id") is None and temp_id is not None:
            resolved = await self.get_resolved_temp_ids(graph_id)
            real_id = resolved.get(str(temp_id))
            if real_id is not None:
                message.node["id"] = real_id
                message.node.pop("temp_id", None)

        list_key = message.list_key
        if list_key not in _ALL_LIST_KEYS:
            logger.warning(
                "Ignoring op with unknown list_key {} on graph {}",
                list_key,
                graph_id,
            )
            return None

        # reject only when the id is an int (assume it already in db) AND
        # that id is NOT currently pending deletion in the accumulator.
        # This check must NOT apply to the legacy NodeUpdatedMessage
        # (changed_fields is None) path that also flows through this method
        # — there a real id is entirely legitimate
        # (e.g. broadcastDecisionRoutingUpdate).
        node_id = message.node.get("id")
        delete_key = _LIST_KEY_TO_DELETE_KEY.get(list_key)
        if isinstance(message, NodeCreatedMessage) and isinstance(node_id, int):
            pending_delete = delete_key is not None and node_id in deleted.get(
                delete_key, []
            )
            if not pending_delete:
                logger.warning(
                    "Rejecting node_created carrying a real id {} on graph {}",
                    node_id,
                    graph_id,
                )
                return OpResult(OpStatus.REJECTED, "stale_id_recreate", relay=False)

        entries: list[dict] = snapshot.setdefault(list_key, [])
        new_entry = copy.copy(message.node)

        # Locate the pre-existing entry (pre-mutation) so a non-superadmin's
        # privileged nested fields get pinned to what's currently stored,
        # not to whatever this upsert is about to write.
        existing_entry = next(
            (
                entry
                for entry in entries
                if _match_entry(entry, new_entry.get("id"), new_entry.get("temp_id"))
            ),
            None,
        )
        # new_entry is a SHALLOW copy of message.node, so this in-place pin also
        # mutates message.node — that's load-bearing: consumers.py::_handle_relay
        # relays message.model_dump() to peers, so peers get the pinned value too.
        # Switching to copy.deepcopy would silently break that (peers would get
        # the unauthorized value while the snapshot holds the pinned one).
        pinned_fields = _pin_privileged_fields(
            existing_entry, new_entry, list_key, is_superadmin
        )
        if pinned_fields:
            # Otherwise-invisible server-side correction — log it. This is
            # the same class of bug (a silent authorization override) that
            # was hard to diagnose precisely because nothing surfaced it.
            logger.info(
                "Pinned privileged field(s) {} on graph {} list_key {} "
                "(non-superadmin upsert reset to authorized value)",
                pinned_fields,
                graph_id,
                list_key,
            )

        if list_key in _SINGLETON_LIST_KEYS:
            _collapse_singleton_entry(entries, new_entry, list_key)
        else:
            _upsert_entry(entries, new_entry)

        # If this node has a real id that was previously deleted, remove it
        # from the accumulator — the node is alive again. Two callers reach
        # here with such an id: the legacy NodeUpdatedMessage path
        # (changed_fields is None), and a NodeCreatedMessage that passed the
        # guard above because its id was still pending deletion (the
        # pre-flush undo case). Either way, dropping it from the accumulator
        # is what keeps the row alive with its original pk.
        entry_id = new_entry.get("id")
        if entry_id is not None:
            if delete_key:
                accumulator: list = deleted.get(delete_key, [])
                if entry_id in accumulator:
                    accumulator.remove(entry_id)

        return APPLIED_OK

    async def _apply_node_merge(
        self,
        snapshot: dict,
        deleted: dict,
        message,
        graph_id: int,
        is_superadmin: bool = False,
    ) -> OpResult:
        """Merge-only handling for a NodeUpdatedMessage carrying changed_fields
        (EST-3020). Never creates a new entry and never resurrects a deleted
        node — a miss is always a rejection, not a fallback to upsert.

        See module-level OpResult for the reject reasons this can return.
        """
        list_key = message.list_key
        if list_key not in _ALL_LIST_KEYS:
            logger.warning(
                "Rejecting merge op with unknown list_key {} on graph {}",
                list_key,
                graph_id,
            )
            return OpResult(OpStatus.REJECTED, "unknown_list_key", relay=False)

        changed_fields = set(message.changed_fields)
        allowed_keys = changed_fields | {"id", "temp_id"}
        node = message.node
        filtered: dict = {}
        for key in allowed_keys:
            if key in node:
                filtered[key] = node[key]
            elif key in changed_fields:
                logger.debug(
                    "_apply_node_merge: changed field {} absent from node "
                    "payload on graph {} — ignoring",
                    key,
                    graph_id,
                )

        if filtered.get("id") is None and filtered.get("temp_id") is None:
            return OpResult(OpStatus.REJECTED, "missing_identity", relay=False)

        overlay = copy.copy(filtered)
        entries: list[dict] = snapshot.setdefault(list_key, [])

        target_index: int | None = None
        if list_key in _SINGLETON_LIST_KEYS:
            if entries:
                target_index = 0
                if entries[0].get("id") is not None:
                    # Never attach a mismatched temp_id to an already-persisted
                    # singleton row.
                    overlay.pop("temp_id", None)
        else:
            ref_id = overlay.get("id")
            ref_temp_id = overlay.get("temp_id")
            for index, existing in enumerate(entries):
                if _match_entry(existing, ref_id, ref_temp_id):
                    target_index = index
                    if existing.get("id") is not None:
                        # Never attach a stale temp_id to an already-persisted
                        # entry — a row must never carry both id and temp_id.
                        overlay.pop("temp_id", None)
                    break

            if target_index is None and ref_temp_id is not None:
                resolved = await self.get_resolved_temp_ids(graph_id)
                real_id = resolved.get(str(ref_temp_id))
                if real_id is not None:
                    for index, existing in enumerate(entries):
                        if _match_entry(existing, real_id, None):
                            target_index = index
                            overlay.pop("temp_id", None)
                            overlay["id"] = real_id
                            break

        if target_index is None:
            return OpResult(OpStatus.REJECTED, "target_not_found", relay=False)

        if message.expected is not None:
            expected_norm = copy.copy(dict(message.expected))
            expected_norm.pop("id", None)
            expected_norm.pop("temp_id", None)
            mismatched = find_mismatched_keys(entries[target_index], expected_norm)

            if mismatched:
                wire_mismatched = [key.removeprefix("metadata.") for key in mismatched]
                return OpResult(
                    OpStatus.REJECTED,
                    "precondition_failed",
                    relay=False,
                    details={"mismatched_fields": wire_mismatched},
                )

        # Pinning happens after the CAS check above — a pin must never mask
        # a legitimate precondition_failed rejection.
        # overlay's nested-field values (e.g. "webhook_trigger") are the SAME
        # dict objects as message.node's, since overlay/filtered are shallow
        # copies. Pinning in place therefore also mutates message.node, which
        # consumers.py::_handle_relay relays as-is — that's how peers receive
        # the pinned value. copy.deepcopy anywhere in that chain would
        # silently make peers get the unauthorized value instead.
        pinned_fields = _pin_privileged_fields(
            entries[target_index], overlay, list_key, is_superadmin
        )
        if pinned_fields:
            # Otherwise-invisible server-side correction — log it. This is
            # the same class of bug (a silent authorization override) that
            # was hard to diagnose precisely because nothing surfaced it.
            logger.info(
                "Pinned privileged field(s) {} on graph {} list_key {} "
                "(non-superadmin merge reset to authorized value)",
                pinned_fields,
                graph_id,
                list_key,
            )

        entries[target_index] = merge_entry(entries[target_index], overlay)
        return APPLIED_OK

    async def apply_op(
        self, graph_id: int, message, *, is_superadmin: bool = False
    ) -> OpResult | None:
        """Mutate the stored superset snapshot according to *message*.

        If no snapshot exists yet (race between seed and op), the op is dropped
        silently — the real state will arrive via seed shortly after.

        All mutation for a given graph_id is serialised with an asyncio.Lock to
        prevent lost-update races in the single async worker.

        is_superadmin gates privileged nested fields (see
        PRIVILEGED_NESTED_FIELDS / _pin_privileged_fields) — defaults to False
        so existing positional call sites keep the pre-fix, most restrictive
        behavior rather than silently trusting an unspecified caller.
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
                is_merge_only = (
                    isinstance(message, NodeUpdatedMessage)
                    and message.changed_fields is not None
                )
                return OpResult(
                    OpStatus.REJECTED, "no_snapshot", relay=not is_merge_only
                )

            deleted: dict = snapshot.setdefault("deleted", _make_empty_deleted())

            if isinstance(message, NodeCreatedMessage) or (
                isinstance(message, NodeUpdatedMessage)
                and message.changed_fields is None
            ):
                result = await self._apply_node_upsert(
                    snapshot, deleted, message, graph_id, is_superadmin=is_superadmin
                )

            elif isinstance(message, NodeUpdatedMessage):
                result = await self._apply_node_merge(
                    snapshot, deleted, message, graph_id, is_superadmin=is_superadmin
                )

            elif isinstance(message, NodesDeletedMessage):
                for ref in message.refs:
                    list_key = ref.list_key
                    if list_key not in _ALL_LIST_KEYS:
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

                    # Cascade: a deleted node's edges/routing refs would
                    # otherwise orphan (edges have no FK cascade; see module
                    # docstring). Only real, persisted node ids can have
                    # persisted edges or routing refs pointing at them.
                    if isinstance(ref.id, int):
                        _cascade_deleted_node_refs(snapshot, deleted, ref.id)

                result = APPLIED_OK

            elif isinstance(message, ConnectionCreatedMessage):
                list_key = message.list_key
                if list_key not in _ALL_LIST_KEYS:
                    logger.warning(
                        "Ignoring op with unknown list_key {} on graph {}",
                        list_key,
                        graph_id,
                    )
                    return

                # A connection create carrying a real DB id is legitimate
                # exactly in the pre-flush undo window — same rule as
                # node_created (see _apply_node_upsert).
                # Once a flush persists the deletion, apply_id_remap removes
                # the id from the accumulator and the pk is dead — a create
                # carrying it again is a stale replay and must be rejected
                connection_id_candidate = message.connection.get("id")
                if isinstance(connection_id_candidate, int):
                    delete_key = _LIST_KEY_TO_DELETE_KEY.get(list_key)
                    pending_delete = (
                        delete_key is not None
                        and connection_id_candidate in deleted.get(delete_key, [])
                    )
                    if not pending_delete:
                        logger.warning(
                            "Rejecting connection_created carrying a real id {} "
                            "on graph {}",
                            connection_id_candidate,
                            graph_id,
                        )
                        return OpResult(
                            OpStatus.REJECTED, "stale_id_recreate", relay=False
                        )

                entries = snapshot.setdefault(list_key, [])
                new_connection = copy.copy(message.connection)

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

                result = APPLIED_OK

            elif isinstance(message, ConnectionDeletedMessage):
                list_key = message.list_key
                if list_key not in _ALL_LIST_KEYS:
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

                result = APPLIED_OK

            elif isinstance(message, ConnectionsDeletedMessage):
                for ref in message.refs:
                    list_key = ref.list_key
                    if list_key not in _ALL_LIST_KEYS:
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

                result = APPLIED_OK

            elif isinstance(message, ConnectionWaypointsUpdatedMessage):
                list_key = message.list_key
                if list_key not in _ALL_LIST_KEYS:
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

                result = APPLIED_OK

            else:
                result = APPLIED_OK

            if result is not None and result.status is OpStatus.APPLIED:
                await self.seed(graph_id, snapshot)
                self._revision[graph_id] = self._revision.get(graph_id, 0) + 1

            return result


def _cascade_deleted_node_refs(snapshot: dict, deleted: dict, node_id: int) -> None:
    """Drop edges and null decision-table routing refs pointing at *node_id*"""
    cascaded_edge_ids: dict[str, list] = {}

    for list_key, ref_fields in _EDGE_NODE_REF_FIELDS.items():
        entries = snapshot.get(list_key, [])
        surviving = []
        delete_key = _LIST_KEY_TO_DELETE_KEY[list_key]
        accumulator: list = deleted.setdefault(delete_key, [])
        for entry in entries:
            references_node = entry is not None and any(
                entry.get(field) == node_id for field in ref_fields
            )
            if references_node:
                entry_id = entry.get("id")
                if entry_id is not None and entry_id not in accumulator:
                    accumulator.append(entry_id)
                    cascaded_edge_ids.setdefault(delete_key, []).append(entry_id)
            else:
                surviving.append(entry)
        snapshot[list_key] = surviving

    nulled_routing_ref_count = 0
    for list_key in _DECISION_TABLE_LIST_KEYS:
        for entry in snapshot.get(list_key, []):
            if entry is None:
                continue
            if entry.get("default_next_node_id") == node_id:
                entry["default_next_node_id"] = None
                nulled_routing_ref_count += 1
            if entry.get("next_error_node_id") == node_id:
                entry["next_error_node_id"] = None
                nulled_routing_ref_count += 1
            for group in entry.get("condition_groups") or []:
                if isinstance(group, dict) and group.get("next_node_id") == node_id:
                    group["next_node_id"] = None
                    nulled_routing_ref_count += 1

    if cascaded_edge_ids or nulled_routing_ref_count:
        logger.debug(
            "_cascade_deleted_node_refs: node_id={} — edge_ids={}, "
            "conditional_edge_ids={}, nulled_routing_refs={}",
            node_id,
            cascaded_edge_ids.get("edge_ids", []),
            cascaded_edge_ids.get("conditional_edge_ids", []),
            nulled_routing_ref_count,
        )


def _make_empty_deleted() -> dict:
    """Return a fresh deleted accumulator with all expected keys."""
    return {delete_key: [] for delete_key in _LIST_KEY_TO_DELETE_KEY.values()}


def _list_keys_exposing_content_hash() -> set[str]:
    """List keys whose GraphSerializer child serializer declares `content_hash`
    as a field — i.e. list keys for which a reseed from the DB would produce
    an entry carrying a content_hash key. Derived from GraphSerializer itself
    (rather than hardcoded) so this stays correct if a serializer's exposure
    of content_hash ever changes.
    """
    from tables.serializers.model_serializers.graph_serializers import GraphSerializer

    exposing_list_keys: set[str] = set()
    for list_key, field in GraphSerializer().fields.items():
        child = getattr(field, "child", None)
        if child is not None and "content_hash" in child.fields:
            exposing_list_keys.add(list_key)
    return exposing_list_keys


@sync_to_async
def _refresh_flushed_content_hashes(snapshot: dict) -> None:
    """Add or refresh each snapshot node/edge entry's content_hash — and any
    nested python_code content_hash — from the row just written to the DB.

    Runs from apply_id_remap after a successful flush. One batched query per
    model. For list keys whose serializer exposes content_hash (mirrored via
    _list_keys_exposing_content_hash(), not hardcoded), the key is added when
    missing (e.g. a node created during the session, whose snapshot entry was
    built from the frontend's node_created payload rather than GraphSerializer)
    and overwritten when already present. List keys whose serializer does NOT
    expose content_hash (e.g. classification_decision_table_node_list,
    code_agent_node_list) are left untouched, so the live snapshot's shape
    keeps matching what a reseed from the DB would produce. Nested python_code
    entries always get the same add-or-update treatment, since PythonCodeSerializer
    exposes content_hash unconditionally wherever it is nested.
    """
    from tables.models.base_models import ContentHashMixin
    from tables.models.graph_models import (
        ClassificationDecisionTableNode,
        ConditionalEdge,
        Edge,
        PythonNode,
        WebhookTriggerNode,
    )
    from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY

    model_by_list_key: dict[str, type] = {
        config.list_key: config.model_class for config in NODE_TYPE_REGISTRY
    }
    # Edges live outside NODE_TYPE_REGISTRY — add explicitly.
    model_by_list_key["edge_list"] = Edge
    model_by_list_key["conditional_edge_list"] = ConditionalEdge

    # Model -> nested PythonCode FK fields whose content_hash also needs refreshing.
    nested_python_code_fields: dict[type, tuple[str, ...]] = {
        PythonNode: ("python_code",),
        WebhookTriggerNode: ("python_code",),
        ConditionalEdge: ("python_code",),
        ClassificationDecisionTableNode: ("pre_python_code", "post_python_code"),
    }

    exposing_list_keys = _list_keys_exposing_content_hash()

    for list_key, model_class in model_by_list_key.items():
        entries = snapshot.get(list_key) or []
        id_to_entry: dict[int, dict] = {
            entry["id"]: entry
            for entry in entries
            if entry is not None and entry.get("id") is not None
        }
        if not id_to_entry:
            continue

        top_level_exposes_content_hash = list_key in exposing_list_keys
        nested_fields = nested_python_code_fields.get(model_class, ())
        queryset = model_class.objects.filter(id__in=id_to_entry.keys())
        if nested_fields:
            queryset = queryset.select_related(*nested_fields)

        for instance in queryset:
            entry = id_to_entry[instance.id]
            if top_level_exposes_content_hash and isinstance(
                instance, ContentHashMixin
            ):
                entry["content_hash"] = instance.content_hash

            for field_name in nested_fields:
                nested_entry = entry.get(field_name)
                nested_instance = getattr(instance, field_name, None)
                if isinstance(nested_entry, dict) and isinstance(
                    nested_instance, ContentHashMixin
                ):
                    nested_entry["content_hash"] = nested_instance.content_hash


@sync_to_async
def _refresh_schedule_node_content_hash(node_id: int) -> str | None:
    """Return the current DB-computed content_hash for a single
    ``ScheduleTriggerNode``, or None if the row no longer exists.

    Focused sibling of ``_refresh_flushed_content_hashes`` — scoped to the
    one node the scheduler just deactivated rather than a whole-snapshot
    batch refresh, since ``apply_scheduler_deactivation`` only ever touches
    one row.
    """
    from tables.models.graph_models import ScheduleTriggerNode

    try:
        node = ScheduleTriggerNode.objects.get(pk=node_id)
    except ScheduleTriggerNode.DoesNotExist:
        return None
    return node.content_hash


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
