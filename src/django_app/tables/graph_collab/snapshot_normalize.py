"""
Helpers for normalising a GraphSerializer READ snapshot into the superset form

The superset adds write-only FK id fields that the read serializer omits but
the bulk-save serializers need.  The nested read objects are kept intact so the
frontend late-join converter can still use them.

Injected fields per node type
==============================

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
    No injection needed.
"""

import copy


def inject_bulk_save_fields(snapshot: dict) -> dict:
    """Return a deep copy of *snapshot* with write-only FK ids injected.

    Operates on the dict produced by ``GraphSerializer(graph).data``.  Does not
    mutate the input.  Safe to call multiple times (idempotent).
    """
    snapshot = copy.deepcopy(snapshot)

    # --- crew_node_list: inject crew_id from nested crew object ---
    for node in snapshot.get("crew_node_list", []):
        crew = node.get("crew")
        if isinstance(crew, dict) and "id" in crew:
            node.setdefault("crew_id", crew["id"])

    # --- schedule_trigger_node_list: coerce schedule.end.type None → "never" ---
    for node in snapshot.get("schedule_trigger_node_list", []):
        schedule = node.get("schedule")
        if isinstance(schedule, dict):
            end = schedule.get("end")
            if isinstance(end, dict) and end.get("type") is None:
                end["type"] = "never"

    return snapshot
