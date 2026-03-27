from drf_yasg import openapi

_node_item = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    description=(
        "Mirrors the single-node endpoint payload. "
        "Omit id for new nodes. "
        "For new nodes, include temp_id (client-generated UUID) so edges in the same "
        "request can reference this node before its real DB id is known."
    ),
)

_edge_item = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    description=(
        "Edge payload using real global node IDs. "
        "For each end (start/end), provide exactly one of: "
        "the real DB node id (start_node_id / end_node_id) for existing nodes, "
        "or a temp UUID (start_temp_id / end_temp_id) matching a temp_id on a new node "
        "in the same request."
    ),
)

_conditional_edge_item = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    description=(
        "ConditionalEdge payload. "
        "Provide exactly one of source_node_id (real DB id) or source_temp_id "
        "(UUID matching a new node's temp_id in this request)."
    ),
)

_id_list = openapi.Schema(
    type=openapi.TYPE_ARRAY,
    items=openapi.Schema(type=openapi.TYPE_INTEGER),
)

SAVE_FLOW_SWAGGER = dict(
    operation_summary="Bulk save all flow nodes and edges",
    operation_description=(
        "Atomically upserts and deletes all nodes/edges for a flow in one request.\n\n"
        "- Entity with `id` → update.\n"
        "- Entity without `id` → create.\n"
        "- IDs in `deleted` → deleted (validated as belonging to this graph).\n\n"
        "FE sends only changed entities. "
        "All entities are validated first. If any fail, the entire request is rejected "
        "and no DB writes happen."
    ),
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "crew_node_list": openapi.Schema(type=openapi.TYPE_ARRAY, items=_node_item),
            "python_node_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_node_item
            ),
            "file_extractor_node_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_node_item
            ),
            "audio_transcription_node_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_node_item
            ),
            "llm_node_list": openapi.Schema(type=openapi.TYPE_ARRAY, items=_node_item),
            "start_node_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_node_item
            ),
            "end_node_list": openapi.Schema(type=openapi.TYPE_ARRAY, items=_node_item),
            "subgraph_node_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_node_item
            ),
            "decision_table_node_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_node_item
            ),
            "graph_note_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_node_item
            ),
            "webhook_trigger_node_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_node_item
            ),
            "telegram_trigger_node_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_node_item
            ),
            "edge_list": openapi.Schema(type=openapi.TYPE_ARRAY, items=_edge_item),
            "conditional_edge_list": openapi.Schema(
                type=openapi.TYPE_ARRAY, items=_conditional_edge_item
            ),
            "deleted": openapi.Schema(
                type=openapi.TYPE_OBJECT,
                description="All keys optional, default []. Edges deleted before nodes.",
                properties={
                    "crew_node_ids": _id_list,
                    "python_node_ids": _id_list,
                    "file_extractor_node_ids": _id_list,
                    "audio_transcription_node_ids": _id_list,
                    "llm_node_ids": _id_list,
                    "start_node_ids": _id_list,
                    "end_node_ids": _id_list,
                    "subgraph_node_ids": _id_list,
                    "decision_table_node_ids": _id_list,
                    "graph_note_ids": _id_list,
                    "webhook_trigger_node_ids": _id_list,
                    "telegram_trigger_node_ids": _id_list,
                    "edge_ids": _id_list,
                    "conditional_edge_ids": _id_list,
                },
            ),
        },
        example={
            "crew_node_list": [
                {
                    "id": 5,
                    "graph": 12,
                    "crew_id": 3,
                    "node_name": "crewnode_5",
                    "input_map": {},
                    "output_variable_path": None,
                    "metadata": {"position": {"x": 100, "y": 200}},
                },
                {
                    "graph": 12,
                    "crew_id": 7,
                    "node_name": "crewnode_new",
                    "input_map": {},
                    "output_variable_path": None,
                    "metadata": {"position": {"x": 400, "y": 200}},
                },
            ],
            "python_node_list": [
                {
                    "id": 9,
                    "graph": 12,
                    "node_name": "pythonnode_9",
                    "input_map": {"input": "variables.user_text"},
                    "output_variable_path": "result",
                    "python_code": {
                        "code": "def main(input): return input.upper()",
                        "libraries": [],
                    },
                    "metadata": {"position": {"x": 700, "y": 200}},
                }
            ],
            "file_extractor_node_list": [],
            "audio_transcription_node_list": [],
            "llm_node_list": [],
            "start_node_list": [
                {
                    "id": 1,
                    "graph": 12,
                    "variables": {"user_text": ""},
                    "metadata": {"position": {"x": -200, "y": 200}},
                }
            ],
            "end_node_list": [
                {
                    "id": 2,
                    "graph": 12,
                    "output_map": {"context": "variables"},
                    "metadata": {"position": {"x": 1000, "y": 200}},
                }
            ],
            "subgraph_node_list": [],
            "decision_table_node_list": [
                {
                    "graph": 12,
                    "node_name": "decision_1",
                    "default_next_node": "crewnode_5",
                    "next_error_node": None,
                    "metadata": {"position": {"x": 250, "y": 400}},
                    "condition_groups": [
                        {
                            "group_name": "group_a",
                            "group_type": "simple",
                            "order": 0,
                            "next_node": "crewnode_new",
                            "conditions": [
                                {
                                    "condition_name": "cond_1",
                                    "order": 0,
                                    "condition": "variables.user_text != ''",
                                }
                            ],
                        }
                    ],
                }
            ],
            "graph_note_list": [
                {
                    "graph": 12,
                    "content": "This flow processes user text through a crew.",
                    "metadata": {"position": {"x": 100, "y": -100}},
                }
            ],
            "webhook_trigger_node_list": [],
            "telegram_trigger_node_list": [],
            "edge_list": [
                {
                    "graph": 12,
                    "start_node_id": 9,
                    "end_temp_id": "372b0d79-4cc2-464e-baf8-c4a982e63af3",
                    "metadata": {},
                },
                {
                    "id": 15,
                    "graph": 12,
                    "start_temp_id": "372b0d79-4cc2-464e-baf8-c4a982e63af3",
                    "end_node_id": 101,
                    "metadata": {},
                },
            ],
            "conditional_edge_list": [],
            "deleted": {
                "crew_node_ids": [8],
                "edge_ids": [14],
            },
        },
    ),
    responses={
        200: openapi.Response(description="Full updated graph state after save."),
        400: openapi.Response(
            description="Validation errors — no DB changes were made.",
            examples={
                "application/json": {
                    "errors": {
                        "crew_node_list": [
                            {
                                "index": 1,
                                "errors": {
                                    "crew_id": ["Invalid crew_id: crew does not exist."]
                                },
                            }
                        ],
                        "deleted": ["crew_node_ids: IDs [8] not found in graph 12"],
                    }
                }
            },
        ),
        404: "Graph not found.",
    },
)
