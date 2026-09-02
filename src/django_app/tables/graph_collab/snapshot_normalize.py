"""
Helpers for normalising a GraphSerializer READ snapshot into the superset form

The superset adds write-only FK id fields that the read serializer omits but
the bulk-save serializers need.  The nested read objects are kept intact so the
frontend late-join converter can still use them.
"""

import copy
from utils.logger import logger

from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY

from tables.graph_collab.constants import (
    _SINGLETON_LIST_KEYS,
    _ALL_LIST_KEYS,
    _DECISION_TABLE_LIST_KEYS,
)
from tables.graph_collab.external_refs import DeadRef, find_dead_external_refs


def inject_bulk_save_fields(snapshot: dict, graph_id: int) -> dict:
    """Return a deep copy of *snapshot* with write-only FK ids injected.

    Operates on the dict produced by ``GraphSerializer(graph).data`` or on a
    snapshot that was mutated by WS ops (which omit the ``graph`` FK).  Does not
    mutate the input.  Safe to call multiple times (idempotent): ``setdefault``
    never overwrites values that are already present.

    Injected fields
    ---------------
    graph (int)
        Injected into every entry across all 13 node lists and both edge lists.
        DB-seeded entries already carry the correct value; op-created entries do
        not — this is what caused ``BulkSaveValidationError {'graph': ['This
        field is required.']}`` on flush.
    crew_id (int)
        Injected into crew_node_list entries from the nested ``crew`` object.
    schedule.end.type ("never")
        Coerced from None when the schedule end type was not set.
    """
    snapshot = copy.deepcopy(snapshot)

    # --- ALL list keys: inject graph FK so op-created entries pass validation ---
    for list_key in _ALL_LIST_KEYS:
        for entry in snapshot.get(list_key, []):
            if entry is None:
                # Corrupted snapshot entry — skip rather than crash.  The DB
                # serializer will reject any null entries during validation and
                # flush_service will return FAILED, retaining the snapshot.
                continue
            entry.setdefault("graph", graph_id)

    # --- crew_node_list: inject crew_id from nested crew object ---
    for node in snapshot.get("crew_node_list", []):
        if node is None:
            continue
        crew = node.get("crew")
        if isinstance(crew, dict) and "id" in crew:
            node.setdefault("crew_id", crew["id"])

    # --- schedule_trigger_node_list: coerce schedule.end.type None → "never" ---
    for node in snapshot.get("schedule_trigger_node_list", []):
        if node is None:
            continue
        schedule = node.get("schedule")
        if isinstance(schedule, dict):
            end = schedule.get("end")
            if isinstance(end, dict) and end.get("type") is None:
                end["type"] = "never"

    for node in snapshot.get("webhook_trigger_node_list", []):
        if node is None:
            continue
        if node.get("webhook_node_auth") is None:
            node.pop("webhook_node_auth", None)

    return snapshot


def reconcile_against_db(payload: dict, graph) -> tuple[dict, list[DeadRef]]:
    """Prune *payload* of references to node rows already gone from the DB.

    Mutates and returns *payload* in place (the caller already owns a
    deep-copied dict from ``inject_bulk_save_fields``, so a second copy here
    would be wasted work). Never mutates the live Redis snapshot — that is a
    separate object owned by the caller; the returned ``list[DeadRef]`` lets
    the caller (flush_service) mirror the same nulling into the live snapshot
    and notify connected editors, since payload-only nulling would leave the
    snapshot poisoned for the next flush.

    Never silently drops without logging — every prune is summarised via
    ``logger.info`` so recovery from drift is auditable.
    """
    pruned_nodes: dict[str, list[int]] = {}
    surviving_node_ids: set[int] = set()

    for config in NODE_TYPE_REGISTRY:
        # Always query existing ids for this node type, even when the payload
        # carries no entries for it: an edge may legitimately reference a DB
        # node of this type that simply wasn't touched by this flush (not
        # every node on the graph is re-submitted every time). Skipping this
        # query when the payload list is empty would make such untouched,
        # perfectly valid nodes look "gone" in step 2 below.
        existing_ids = set(
            config.model_class.objects.filter(graph=graph).values_list("id", flat=True)
        )
        surviving_node_ids |= existing_ids

        entries = payload.get(config.list_key) or []
        if not entries:
            continue

        requested_ids = {
            entry["id"]
            for entry in entries
            if entry is not None and isinstance(entry.get("id"), int)
        }

        gone_ids = requested_ids - existing_ids
        if gone_ids:
            payload[config.list_key] = [
                entry
                for entry in entries
                if entry is None or entry.get("id") not in gone_ids
            ]
            pruned_nodes[config.list_key] = sorted(gone_ids)

    collapsed_singletons = _collapse_singleton_lists(payload)

    pruned_edges: dict[str, list] = {}
    deleted: dict = payload.setdefault("deleted", {})

    edge_entries = payload.get("edge_list") or []
    if edge_entries:
        surviving_edges = []
        gone_edge_refs = []
        for entry in edge_entries:
            if entry is None:
                surviving_edges.append(entry)
                continue
            start_id = entry.get("start_node_id")
            end_id = entry.get("end_node_id")
            dangling = (
                isinstance(start_id, int) and start_id not in surviving_node_ids
            ) or (isinstance(end_id, int) and end_id not in surviving_node_ids)
            if dangling:
                gone_edge_refs.append(entry.get("id") or entry.get("temp_id") or entry)
                _enqueue_deletion(deleted, "edge_ids", entry.get("id"))
            else:
                surviving_edges.append(entry)
        if gone_edge_refs:
            payload["edge_list"] = surviving_edges
            pruned_edges["edge_list"] = gone_edge_refs

    conditional_edge_entries = payload.get("conditional_edge_list") or []
    if conditional_edge_entries:
        surviving_conditional_edges = []
        gone_conditional_edge_refs = []
        for entry in conditional_edge_entries:
            if entry is None:
                surviving_conditional_edges.append(entry)
                continue
            source_id = entry.get("source_node_id")
            dangling = (
                isinstance(source_id, int) and source_id not in surviving_node_ids
            )
            if dangling:
                gone_conditional_edge_refs.append(
                    entry.get("id") or entry.get("temp_id") or entry
                )
                _enqueue_deletion(deleted, "conditional_edge_ids", entry.get("id"))
            else:
                surviving_conditional_edges.append(entry)
        if gone_conditional_edge_refs:
            payload["conditional_edge_list"] = surviving_conditional_edges
            pruned_edges["conditional_edge_list"] = gone_conditional_edge_refs

    nulled_routing_refs = _null_dangling_routing_refs(payload, surviving_node_ids)

    # External (non-graph) FK/M2M refs — LLMConfig, subgraph Graph, secrets,
    # ngrok config, AgentDefinition, Surface — whose target was deleted or
    # moved to another org out-of-band. Unlike the pruning above, the node row
    # itself survives; only the stale ref gets nulled. See external_refs.py.
    dead_external_refs = find_dead_external_refs(payload, graph)

    if (
        pruned_nodes
        or pruned_edges
        or nulled_routing_refs
        or collapsed_singletons
        or dead_external_refs
    ):
        graph_id = getattr(graph, "id", graph)
        logger.info(
            "reconcile_against_db: pruned stale refs for graph {} — "
            "nodes={}, edges={}, nulled_routing_refs={}, collapsed_singletons={}, "
            "nulled_external_refs={}",
            graph_id,
            pruned_nodes,
            pruned_edges,
            nulled_routing_refs,
            collapsed_singletons,
            len(dead_external_refs),
        )

    return payload, dead_external_refs


def _collapse_singleton_lists(payload: dict) -> dict[str, int]:
    """Collapse each ``_SINGLETON_LIST_KEYS`` list in *payload* to one entry.

    Self-heals graphs that were already corrupted (duplicate start/end
    entries) before the op-time dedup in ``graph_state_service.apply_op``
    shipped. Prefers the entry carrying a real int ``id`` (the persisted
    row); the rest are unpersisted duplicate creates, so they are simply
    dropped — there is no DB row to reap into ``deleted``.

    Mutates *payload* in place. Returns ``{list_key: dropped_count}`` for
    lists that actually had more than one entry, for logging.
    """
    collapsed: dict[str, int] = {}
    for list_key in _SINGLETON_LIST_KEYS:
        entries = payload.get(list_key) or []
        if len(entries) <= 1:
            continue

        with_real_id = [
            entry
            for entry in entries
            if entry is not None and isinstance(entry.get("id"), int)
        ]
        survivor = with_real_id[0] if with_real_id else entries[0]

        collapsed[list_key] = len(entries) - 1
        payload[list_key] = [survivor]

    return collapsed


def _enqueue_deletion(deleted: dict, delete_key: str, entry_id: int | None) -> None:
    """Append *entry_id* to ``deleted[delete_key]`` if it's a real id, deduped.

    No-op when *entry_id* is None (temp-only entry — never persisted, so
    there is no DB row to delete).
    """
    if entry_id is None:
        return
    accumulator: list = deleted.setdefault(delete_key, [])
    if entry_id not in accumulator:
        accumulator.append(entry_id)


def _null_dangling_routing_refs(payload: dict, surviving_node_ids: set[int]) -> dict:
    """Null decision-table routing refs pointing at a node gone from the DB.

    Checks ``default_next_node_id``, ``next_error_node_id``, and every
    ``condition_groups[].next_node_id`` on each decision-table-like entry in
    *payload*. Mutates entries in place. Returns a summary of what was
    nulled, keyed by list_key, for logging.
    """
    nulled: dict[str, list[dict]] = {}
    for list_key in _DECISION_TABLE_LIST_KEYS:
        for entry in payload.get(list_key) or []:
            if entry is None:
                continue
            entry_nulled: dict = {}

            for field in ("default_next_node_id", "next_error_node_id"):
                value = entry.get(field)
                if isinstance(value, int) and value not in surviving_node_ids:
                    entry[field] = None
                    entry_nulled[field] = value

            nulled_group_refs = []
            for group in entry.get("condition_groups") or []:
                if not isinstance(group, dict):
                    continue
                value = group.get("next_node_id")
                if isinstance(value, int) and value not in surviving_node_ids:
                    group["next_node_id"] = None
                    nulled_group_refs.append(value)
            if nulled_group_refs:
                entry_nulled["condition_groups.next_node_id"] = nulled_group_refs

            if entry_nulled:
                entry_ref = entry.get("id") or entry.get("temp_id")
                nulled.setdefault(list_key, []).append(
                    {"entry": entry_ref, **entry_nulled}
                )

    return nulled
