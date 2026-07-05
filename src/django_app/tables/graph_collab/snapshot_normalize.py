"""
Helpers for normalising a GraphSerializer READ snapshot into the superset form

The superset adds write-only FK id fields that the read serializer omits but
the bulk-save serializers need.  The nested read objects are kept intact so the
frontend late-join converter can still use them.

Injected fields per node type
==============================

ALL list keys (nodes + edges)
------------------------------
  - graph (int)  — FK to the parent Graph row.  All node serializers and both
    edge serializers (EdgeSerializer / ConditionalEdgeSerializer) declare
    ``fields = "__all__"`` and therefore require ``graph`` as a writable field.
    DB-seeded entries carry it already; WS-op–created entries do NOT (the FE
    payloads omit it in nodeToWsPayload / connectionToWsPayload).  Injected via
    ``setdefault`` so seeded entries are never clobbered and the function stays
    idempotent.

crew_node_list
--------------
  - crew_id (int)  — write-only on CrewNodeSerializer (crew is read-only nested).
    Injected from crew["id"].  Without it CrewNodeBulkSerializer fails validation
    because crew_id has no default and is required.

schedule_trigger_node_list
--------------------------
  - schedule.end.type (str → "never")  — ScheduleTriggerNodeSerializer renders
    end_type=None as schedule.end.type=null when the node was saved without a
    schedule.  _ScheduleEndInputSerializer.type is a required ChoiceField; null
    fails validation.  Coerce None → "never" (the safe default that passes
    validation and matches the model's NEVER constant).

All other node types
--------------------
  - code_agent_node_list : llm_config is a plain PrimaryKeyRelatedField (int FK)
    on CodeAgentNodeSerializer — emitted as-is by the read serializer.  No injection needed.
  - subgraph_node_list : subgraph is a plain PK field — emitted as int.  No injection needed.
  - python_node_list / webhook_trigger_node_list / conditional_edge_list :
    python_code is a nested writable serializer that serialises both read and
    write — emitted as a full nested object that the bulk serializer accepts.
    No injection needed.
  - start_node_list / end_node_list / file_extractor_node_list /
    audio_transcription_node_list / graph_note_list /
    telegram_trigger_node_list / decision_table_node_list :
    All fields are either scalar, nested writable, or already have defaults.
    No injection needed.
  - edge_list : start_node_id and end_node_id are plain integer fields.
    No injection needed beyond graph.

reconcile_against_db()
=======================
Prunes a flush payload of references to node rows that no longer exist in the
DB. This self-heals drift caused by an external CASCADE delete on a node's
related row (e.g. deleting a ``Crew`` cascades its ``CrewNode``) that leaves
the live Redis snapshot holding a stale node entry and/or stale edge refs to
it. Without this, ``GraphBulkSaveInputSerializer``/``GraphBulkSaveService``
would reject the entire flush every tick — permanently wedging autosave.

Generic across every node type in ``NODE_TYPE_REGISTRY`` (not crew-specific):
any node model with an externally-CASCADE-able FK can hit this same drift.
Payload-only — the retained Redis snapshot is never mutated here.
"""

import copy

from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY
from utils.logger import logger

# All snapshot list keys that require ``graph`` injection.
# Defined here (not imported from graph_state_service) to avoid a circular
# import: graph_state_service already imports this module.
_ALL_LIST_KEYS: frozenset[str] = frozenset(
    [
        "crew_node_list",
        "python_node_list",
        "file_extractor_node_list",
        "audio_transcription_node_list",
        "start_node_list",
        "end_node_list",
        "subgraph_node_list",
        "decision_table_node_list",
        "graph_note_list",
        "webhook_trigger_node_list",
        "telegram_trigger_node_list",
        "schedule_trigger_node_list",
        "code_agent_node_list",
        "classification_decision_table_node_list",
        "edge_list",
        "conditional_edge_list",
    ]
)


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

    return snapshot


def reconcile_against_db(payload: dict, graph) -> dict:
    """Prune *payload* of references to node rows already gone from the DB.

    Mutates and returns *payload* in place (the caller already owns a
    deep-copied dict from ``inject_bulk_save_fields``, so a second copy here
    would be wasted work). Never mutates the live Redis snapshot — that is a
    separate object owned by the caller.

    Two-step prune, driven by ``NODE_TYPE_REGISTRY`` so it covers every node
    type generically (not just ``crew_node_list``):

    1. For each ``<type>_node_list``, drop any entry carrying a real int ``id``
       that no longer exists in the DB for this graph. New entries (no ``id``,
       i.e. temp_id-only creates) are left untouched.
    2. Compute the set of node ids that still exist in the DB for this graph
       (across all node types) and drop any ``edge_list`` / ``conditional_edge_list``
       entry whose real endpoint ref (``start_node_id``/``end_node_id`` on
       edges, ``source_node_id`` on conditional edges — conditional edges have
       no ``target_node_id`` field) points at an id no longer in that set.
       temp_id-only refs (new, not-yet-persisted endpoints) are left untouched.

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

    pruned_edges: dict[str, list] = {}

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
            else:
                surviving_conditional_edges.append(entry)
        if gone_conditional_edge_refs:
            payload["conditional_edge_list"] = surviving_conditional_edges
            pruned_edges["conditional_edge_list"] = gone_conditional_edge_refs

    if pruned_nodes or pruned_edges:
        graph_id = getattr(graph, "id", graph)
        logger.info(
            "reconcile_against_db: pruned stale refs for graph {} — nodes={}, edges={}",
            graph_id,
            pruned_nodes,
            pruned_edges,
        )

    return payload
