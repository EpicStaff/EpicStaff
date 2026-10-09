from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers

from tables.serializers.serializers import RunSessionSerializer, SessionTestRunSerializer
from tables.serializers.storage_serializers import SessionOutputFileSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

RUN_SESSION_POST = {
    "summary": "Start a new session",
    "description": (
        "Starts a new session for the given flow (`graph_id` or `graph_uuid`). "
        "Caller and organization are derived from the authenticated request. "
        "Requires READ on flows. Uploaded `files` are base64-encoded into "
        "`variables` under the `files` key."
    ),
    "request": RunSessionSerializer,
    "examples": [
        OpenApiExample(
            "Run session",
            value={
                "graph_id": 0,
                "variables": {
                    "variables": {"context": {}},
                    "persistent_variables": {},
                },
                "files": {},
            },
            request_only=True,
        ),
    ],
    "responses": {
        201: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Session successfully started.",
            examples=[
                OpenApiExample(
                    "Session started",
                    value={"session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
                    response_only=True,
                    status_codes=["201"],
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description=(
                "Total file size exceeds the limit, validation failed, or the "
                "session failed to start."
            ),
            examples=[
                OpenApiExample(
                    "File size exceeded",
                    value={"files": ["Total files size exceeds 10.00 MB (got 15.32 MB)"]},
                    response_only=True,
                    status_codes=["400"],
                ),
                OpenApiExample(
                    "Validation error",
                    value={"graph_id": ["A valid integer is required."]},
                    response_only=True,
                    status_codes=["400"],
                ),
                OpenApiExample(
                    "Internal error",
                    value={"error": "Connection refused"},
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Caller lacks READ on flows in the flow's organization.",
            examples=[
                OpenApiExample(
                    "Permission denied",
                    value={
                        "status_code": 403,
                        "code": "permission_denied",
                        "message": "You do not have permission to perform this action.",
                    },
                    response_only=True,
                    status_codes=["403"],
                ),
            ],
        ),
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description=(
                "No flow exists for the provided `graph_id` or `graph_uuid`, or it belongs "
                "to an organization the caller is not a member of."
            ),
            examples=[
                OpenApiExample(
                    "Graph not found",
                    value={
                        "status_code": 404,
                        "code": "graph_not_found",
                        "message": "Provided graph does not exist",
                    },
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
}

RUN_SESSION_TEST_POST = {
    "summary": "Test-run a flow from a trigger node",
    "description": (
        "Starts a session at the given trigger node as if `payload` had been delivered "
        "to it, without the HTTP ingress, tunnel or webhook authentication. The node "
        "must belong to `graph_id` in the active organization. The session is recorded "
        "with the node's trigger type and `is_test_run: true`. Requires UPDATE on flows. "
        "Webhook payloads are passed to the flow as `trigger_payload`; Telegram payloads "
        "as `telegram_payload` and may only use the field parents and fields selected "
        "on the node, plus the update envelope key `update_id`, which is accepted with "
        "any value and passed through unchanged."
    ),
    "request": SessionTestRunSerializer,
    "examples": [
        OpenApiExample(
            "Webhook trigger",
            value={
                "graph_id": 12,
                "node_type": "webhook-trigger",
                "node_id": 345,
                "payload": {"order_id": 42, "status": "paid"},
            },
            request_only=True,
        ),
        OpenApiExample(
            "Telegram trigger",
            value={
                "graph_id": 12,
                "node_type": "telegram-trigger",
                "node_id": 346,
                "payload": {
                    "update_id": 900001,
                    "message": {"text": "hello", "chat": {"id": 1001}},
                },
            },
            request_only=True,
        ),
    ],
    "responses": {
        201: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Session successfully started.",
            examples=[
                OpenApiExample(
                    "Session started",
                    value={"session_id": 981},
                    response_only=True,
                    status_codes=["201"],
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description=(
                "Validation failed, the payload does not fit the node, the "
                "`X-Organization-Id` header is missing, or the session failed to start."
            ),
            examples=[
                OpenApiExample(
                    "Payload is not an object",
                    value={
                        "status_code": 400,
                        "code": "invalid",
                        "message": "payload: Test payload must be a JSON object.",
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
                OpenApiExample(
                    "Payload does not fit the Telegram node",
                    value={
                        "status_code": 400,
                        "code": "test_run_payload_invalid",
                        "message": "payload: 'message.photo': field not selected on this node",
                        "errors": ["'message.photo': field not selected on this node"],
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Requires UPDATE on flows in the active organization.",
            examples=[
                OpenApiExample(
                    "Permission denied",
                    value={
                        "status_code": 403,
                        "code": "permission_denied",
                        "message": "You do not have permission to perform this action.",
                    },
                    response_only=True,
                    status_codes=["403"],
                ),
            ],
        ),
        404: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description=(
                "No trigger node of `node_type` with `node_id` exists in `graph_id` "
                "within the active organization."
            ),
            examples=[
                OpenApiExample(
                    "Node not found",
                    value={
                        "status_code": 404,
                        "code": "not_found",
                        "message": "Not found.",
                    },
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
}

RUN_SESSION_SSE_GET = {
    "summary": "Subscribe to real-time updates via SSE",
    "description": (
        "Starts a **Server-Sent Events (SSE)** stream for a given run session. "
        "Continuously pushes the following event types:\n"
        "- **messages**: New or historical graph session messages\n"
        "- **status**: Session status updates\n"
        "- **done**: The session has finished and the stream is closing; do not reconnect\n"
        "- **fatal-error**: If the view crashes, so the frontend can close the connection\n\n"
        "Note: This is a streaming endpoint and won't produce a visible response in Swagger UI. "
        "Use `?test=true` to receive a few finite sample events."
    ),
    "parameters": [
        OpenApiParameter(
            name="test",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.BOOL,
            description="If true, returns 3 sample events and closes the stream. Useful for Swagger.",
            required=False,
        ),
    ],
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="SSE stream of real-time events (text/event-stream).",
            examples=[
                OpenApiExample(
                    "messages event",
                    value={
                        "event": "messages",
                        "data": {
                            "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                            "session_id": 42,
                            "message_data": {
                                "message_type": "finish",
                                "content": "Task completed successfully.",
                            },
                        },
                    },
                    response_only=True,
                    status_codes=["200"],
                ),
                OpenApiExample(
                    "status event",
                    value={
                        "event": "status",
                        "data": {
                            "session_id": 42,
                            "status": "running",
                            "status_data": {},
                        },
                    },
                    response_only=True,
                    status_codes=["200"],
                ),
                OpenApiExample(
                    "done event",
                    value={"event": "done", "data": {"session_id": 42}},
                    response_only=True,
                    status_codes=["200"],
                ),
                OpenApiExample(
                    "fatal-error event",
                    value={
                        "event": "fatal-error",
                        "data": {"detail": "Unexpected server error."},
                    },
                    response_only=True,
                    status_codes=["200"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}

SESSION_LIST_GET = {
    "summary": "List sessions",
    "description": (
        "Returns a paginated, filterable, orderable list of sessions. "
        "Pass `detailed=false` to get lightweight records (minimal fields + `has_output_files`). "
        "Defaults to full session detail (`detailed=true`). "
        "The `detailed=true` behaviour is deprecated and will be removed in a future version."
    ),
    "parameters": [
        OpenApiParameter(
            name="detailed",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.BOOL,
            description="Whether to include all session details. Set to `false` to return only minimal fields. The `true` value is deprecated and will be removed in a future version.",
            required=False,
        ),
        OpenApiParameter(
            name="is_test_run",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.BOOL,
            description=(
                "`true` returns only editor test runs (sessions started from a webhook or "
                "Telegram trigger node). `false` returns every other session, including "
                "sessions without a trigger record. Omit to return both. Any other value is a 400."
            ),
            required=False,
        ),
    ],
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="List of sessions. Shape depends on the `detailed` query param.",
            examples=[
                OpenApiExample(
                    "Full session (detailed=true)",
                    value={
                        "count": 0,
                        "next": "string",
                        "previous": "string",
                        "results": [
                            {
                                "id": 0,
                                "status": "string",
                                "status_updated_at": "2024-01-01T00:00:00Z",
                                "time_to_live": 0,
                                "finished_at": "2024-01-01T00:00:00Z",
                                "status_data": {},
                                "variables": {},
                                "created_at": "2024-01-01T00:00:00Z",
                                "graph_schema": {
                                    "name": "string",
                                    "end_node": None,
                                    "graph_id": 0,
                                    "edge_list": [],
                                    "entrypoint": "string",
                                    "llm_node_list": [],
                                    "python_node_list": [],
                                    "subgraph_node_list": [],
                                    "conditional_edge_list": [],
                                    "decision_table_node_list": [],
                                    "file_extractor_node_list": [],
                                    "key_value_node_list": [],
                                    "audio_transcription_node_list": [],
                                    "webhook_trigger_node_data_list": [],
                                    "telegram_trigger_node_data_list": [],
                                },
                                "entrypoint": None,
                                "token_usage": {
                                    "total_tokens": 0,
                                    "prompt_tokens": 0,
                                    "completion_tokens": 0,
                                    "successful_requests": 0,
                                    "cached_prompt_tokens": 0,
                                    "total_cost_usd": 0.0,
                                },
                                "graph": 0,
                                "parent_session": None,
                                "graph_user": None,
                                "trigger": {
                                    "trigger_type": "manual",
                                    "trigger_id": None,
                                    "is_test_run": False,
                                },
                                "principal": {
                                    "kind": "user",
                                    "user": 7,
                                    "api_key": None,
                                    "email": "a@b.com",
                                },
                            }
                        ],
                    },
                    response_only=True,
                    status_codes=["200"],
                ),
                OpenApiExample(
                    "Light session (detailed=false)",
                    value={
                        "count": 0,
                        "next": "string",
                        "previous": "string",
                        "results": [
                            {
                                "id": 0,
                                "graph_id": 0,
                                "graph_name": "string",
                                "status": "string",
                                "status_updated_at": "2024-01-01T00:00:00Z",
                                "created_at": "2024-01-01T00:00:00Z",
                                "finished_at": "2024-01-01T00:00:00Z",
                                "parent_session": None,
                                "has_output_files": True,
                                "trigger": {
                                    "trigger_type": "manual",
                                    "trigger_id": None,
                                    "is_test_run": False,
                                },
                            }
                        ],
                    },
                    response_only=True,
                    status_codes=["200"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}

SESSION_RETRIEVE_GET = {
    "summary": "Retrieve a session",
    "description": "Returns full details of a single session by its ID.",
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Session details.",
            examples=[
                OpenApiExample(
                    "Session details",
                    value={
                        "id": 0,
                        "status": "string",
                        "status_updated_at": "2024-01-01T00:00:00Z",
                        "time_to_live": 0,
                        "finished_at": "2024-01-01T00:00:00Z",
                        "status_data": {},
                        "variables": {},
                        "created_at": "2024-01-01T00:00:00Z",
                        "graph_schema": {
                            "name": "string",
                            "end_node": None,
                            "graph_id": 0,
                            "edge_list": [],
                            "entrypoint": "string",
                            "llm_node_list": [],
                            "crew_node_list": [],
                            "python_node_list": [],
                            "subgraph_node_list": [],
                            "code_agent_node_list": [],
                            "conditional_edge_list": [],
                            "decision_table_node_list": [],
                            "file_extractor_node_list": [],
                            "audio_transcription_node_list": [],
                            "webhook_trigger_node_data_list": [],
                            "telegram_trigger_node_data_list": [],
                        },
                        "entrypoint": None,
                        "token_usage": {
                            "total_tokens": 0,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "successful_requests": 0,
                            "cached_prompt_tokens": 0,
                            "total_cost_usd": 0.0,
                        },
                        "graph": 0,
                        "parent_session": None,
                        "graph_user": None,
                    },
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Session not found.",
            examples=[
                OpenApiExample(
                    "Not found",
                    value={"detail": "No Session matches the given query."},
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
}

SESSION_DESTROY_DELETE = {
    "summary": "Delete a session",
    "description": "Permanently deletes a single session by its ID.",
    "responses": {
        204: OpenApiResponse(description="Session deleted — no content returned."),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Session not found.",
            examples=[
                OpenApiExample(
                    "Not found",
                    value={"detail": "No Session matches the given query."},
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
}

SESSION_STATUSES_GET = {
    "summary": "Get session status counts grouped by graph",
    "description": (
        "Returns a mapping of `graph_id` to an object of status → count pairs "
        "for all sessions matching the current filter parameters."
    ),
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Mapping of graph_id to status counts.",
            examples=[
                OpenApiExample(
                    "Status counts",
                    value={
                        "7": {"end": 5, "error": 1, "run": 2},
                        "12": {"end": 3, "pending": 1},
                    },
                    response_only=True,
                    status_codes=["200"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}

SESSION_BULK_DELETE_POST = {
    "summary": "Bulk delete sessions",
    "description": (
        "Deletes the requested sessions that belong to the active organization in a single atomic transaction. "
        "`ids` echoes the requested IDs verbatim, while `deleted` counts the requested IDs that were deleted — "
        "IDs that don't exist or belong to another organization are silently skipped, so `deleted` may be less than `len(ids)`. "
        "Sub-sessions of a deleted session are deleted with it; they count toward `deleted` only when their own ID was requested."
    ),
    "request": inline_serializer(
        name="SessionBulkDeleteRequest",
        fields={
            "ids": drf_serializers.ListField(child=drf_serializers.IntegerField()),
        },
    ),
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Sessions successfully deleted.",
            examples=[
                OpenApiExample(
                    "Deleted",
                    value={"deleted": 3, "ids": [1, 2, 3]},
                    response_only=True,
                    status_codes=["200"],
                ),
                OpenApiExample(
                    "Partially deleted",
                    value={"deleted": 2, "ids": [1, 2, 99]},
                    response_only=True,
                    status_codes=["200"],
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="`ids` is missing, not a list, or contains non-integer values.",
            examples=[
                OpenApiExample(
                    "Invalid ids",
                    value={"detail": "ids must be a list of integers."},
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}

SESSION_WARNINGS_GET = {
    "summary": "Get session warnings",
    "description": "Returns warning messages recorded for a session, if any.",
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Session warnings retrieved successfully.",
            examples=[
                OpenApiExample(
                    "Warnings present",
                    value={"messages": ["user_vars_with_no_user"]},
                    response_only=True,
                    status_codes=["200"],
                ),
                OpenApiExample(
                    "No warnings",
                    value=None,
                    response_only=True,
                    status_codes=["200"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Session not found.",
            examples=[
                OpenApiExample(
                    "Not found",
                    value={"detail": "No Session matches the given query."},
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
}

STOP_SESSION_POST = {
    "summary": "Stop a running session",
    "description": "Sends a stop signal to the session identified by its session ID. The signal must be received by all required listeners (manager and crew); if fewer than expected acknowledge, the session is marked as errored.",
    "responses": {
        204: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Session stopped — no content returned.",
            examples=[
                OpenApiExample(
                    "Session stopped",
                    value=None,
                    response_only=True,
                    status_codes=["204"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description=(
                "No session with this ID, or it belongs to an organization the caller "
                "is not a member of."
            ),
            examples=[
                OpenApiExample(
                    "Session not found",
                    value={
                        "status_code": 404,
                        "code": "session_not_found",
                        "message": "Session not found.",
                    },
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
}

GET_UPDATES_GET = {
    "summary": "Get session status update",
    "description": "Returns the current status of a session identified by its session ID.",
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Session details retrieved successfully.",
            examples=[
                OpenApiExample(
                    "Session status",
                    value={"status": "running"},
                    response_only=True,
                    status_codes=["200"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description=(
                "No session with this ID, or it belongs to an organization the caller "
                "is not a member of."
            ),
            examples=[
                OpenApiExample(
                    "Session not found",
                    value={
                        "status_code": 404,
                        "code": "session_not_found",
                        "message": "Session not found.",
                    },
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
}

SESSION_OUTPUT_FILES_GET = {
    "summary": "List session output files",
    "description": (
        "Returns all storage files recorded as output during the given session, "
        "ordered by the time they were added."
    ),
    "responses": {
        200: SessionOutputFileSerializer(many=True),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Session not found.",
            examples=[
                OpenApiExample(
                    "Not found",
                    value={"detail": "No Session matches the given query."},
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
}
