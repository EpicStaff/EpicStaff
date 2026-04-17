from drf_spectacular.utils import OpenApiExample, OpenApiResponse, inline_serializer
from rest_framework import serializers as drf_serializers

_id_list_field = drf_serializers.ListField(
    child=drf_serializers.IntegerField(), required=False
)

SAVE_FLOW_SWAGGER = dict(
    summary="Bulk save all flow nodes and edges",
    description=(
        "Atomically upserts and deletes all nodes/edges for a flow in one request.\n\n"
        "- Entity with `id` → update.\n"
        "- Entity without `id` → create.\n"
        "- IDs in `deleted` → deleted (validated as belonging to this graph).\n\n"
        "FE sends only changed entities. "
        "All entities are validated first. If any fail, the entire request is rejected "
        "and no DB writes happen."
    ),
    request=inline_serializer(
        name="SaveFlowRequest",
        fields={
            "code_agent_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "crew_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "python_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "file_extractor_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "audio_transcription_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "llm_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "start_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "end_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "subgraph_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "decision_table_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "graph_note_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "webhook_trigger_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "telegram_trigger_node_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "edge_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "conditional_edge_list": drf_serializers.ListField(
                child=drf_serializers.DictField(), required=False
            ),
            "deleted": inline_serializer(
                name="DeletedIds",
                fields={
                    "code_agent_node_ids": _id_list_field,
                    "crew_node_ids": _id_list_field,
                    "python_node_ids": _id_list_field,
                    "file_extractor_node_ids": _id_list_field,
                    "audio_transcription_node_ids": _id_list_field,
                    "llm_node_ids": _id_list_field,
                    "start_node_ids": _id_list_field,
                    "end_node_ids": _id_list_field,
                    "subgraph_node_ids": _id_list_field,
                    "decision_table_node_ids": _id_list_field,
                    "graph_note_ids": _id_list_field,
                    "webhook_trigger_node_ids": _id_list_field,
                    "telegram_trigger_node_ids": _id_list_field,
                    "edge_ids": _id_list_field,
                    "conditional_edge_ids": _id_list_field,
                },
                required=False,
            ),
        },
    ),
    examples=[
        OpenApiExample(
            name="Typical bulk save",
            value={
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
                        "default_next_node_id": 5,
                        "next_error_node_id": None,
                        "metadata": {"position": {"x": 250, "y": 400}},
                        "condition_groups": [
                            {
                                "group_name": "group_a",
                                "group_type": "simple",
                                "order": 0,
                                "expression": None,
                                "manipulation": None,
                                "next_node_id": 9,
                            },
                            {
                                "group_name": "group_b",
                                "group_type": "complex",
                                "order": 1,
                                "expression": "score * 0.5",
                                "manipulation": "round_down",
                                "next_node_temp_id": "372b0d79-4cc2-464e-baf8-c4a982e63af3",
                            },
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
            request_only=True,
        )
    ],
    responses={
        200: OpenApiResponse(description="Full updated graph state after save."),
        400: OpenApiResponse(
            description="Validation errors — no DB changes were made."
        ),
        404: OpenApiResponse(description="Graph not found."),
    },
)
