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
"""

import copy

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
