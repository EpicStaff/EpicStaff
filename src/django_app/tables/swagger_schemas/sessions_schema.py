from drf_spectacular.utils import (
    OpenApiResponse,
    OpenApiExample,
    OpenApiParameter,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers
from tables.serializers.model_serializers import (
    SessionSerializer,
    SessionLightSerializer,
)
from tables.serializers.serializers import AnswerToLLMSerializer, RunSessionSerializer
from tables.serializers.storage_serializers import SessionOutputFileSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

ANSWER_TO_LLM = dict(
    summary="Submit user answer to a waiting LLM session",
    description="Sends the user's text response to an active session that is paused and waiting for human input (status = `wait_for_user`). The answer is registered as a session message and forwarded via Redis to the appropriate crew node.",
    request=AnswerToLLMSerializer,
    responses={
        202: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Answer accepted.",
            examples=[
                OpenApiExample(
                    "Answer accepted",
                    value={},
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Validation error — one or more request fields are missing or invalid.",
            examples=[
                OpenApiExample(
                    "Validation error",
                    value={
                        "session_id": ["This field is required."],
                        "answer": ["This field may not be blank."],
                    },
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="No session exists for the given `session_id`.",
            examples=[
                OpenApiExample(
                    "Session not found",
                    value="Session not found",
                    response_only=True,
                ),
            ],
        ),
        418: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="The session exists but is not currently waiting for user input (status != `wait_for_user`).",
            examples=[
                OpenApiExample(
                    "Wrong session status",
                    value="Session status is not wait_for_user",
                    response_only=True,
                ),
            ],
        ),
    },
)

RUN_SESSION_POST = dict(
    summary="Start a new session",
    description=(
        "Starts a new session for the given flow (identified by `graph_id` or `graph_uuid`). "
        "Optionally accepts `variables`, uploaded `files`, and a `username` (interpreted as "
        "the user's email) to bind an OrganizationUser context. Files are base64-encoded and "
        "merged into variables under the `files` key. Organization and user persistent "
        "variables are applied on top of request variables before the session is dispatched."
    ),
    request=RunSessionSerializer,
    examples=[
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
    responses={
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
                "Bad request — total file size exceeds the limit, "
                "serializer validation failed, username provided but no GraphOrganization "
                "exists for this flow, or an internal error occurred while starting the session."
            ),
            examples=[
                OpenApiExample(
                    "File size exceeded",
                    value={
                        "files": ["Total files size exceeds 10.00 MB (got 15.32 MB)"]
                    },
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
                    "No GraphOrganization for flow",
                    value={"message": "No GraphOrganization exists for this flow."},
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
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Graph not found, or the specified user does not exist or does not belong to the graph's organization.",
            examples=[
                OpenApiExample(
                    "Graph not found",
                    value={"message": "Provided graph does not exist"},
                    response_only=True,
                    status_codes=["404"],
                ),
                OpenApiExample(
                    "User not found in organization",
                    value={
                        "message": "Provided user does not exist or does not belong to organization Acme Corp"
                    },
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
)

RUN_SESSION_SSE_GET = dict(
    summary="Subscribe to real-time updates via SSE",
    description=(
        "Starts a **Server-Sent Events (SSE)** stream for a given run session. "
        "Continuously pushes the following event types:\n"
        "- **messages**: New or historical graph session messages\n"
        "- **status**: Session status updates\n"
        "- **memory**: Memory entries related to this session\n"
        "- **fatal-error**: If the view crashes, so the frontend can close the connection\n\n"
        "Note: This is a streaming endpoint and won't produce a visible response in Swagger UI. "
        "Use `?test=true` to receive a few finite sample events."
    ),
    parameters=[
        OpenApiParameter(
            name="test",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.BOOL,
            description="If true, returns 3 sample events and closes the stream. Useful for Swagger.",
            required=False,
        ),
    ],
    responses={
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
                                "sse_visible": True,
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
                    "memory event",
                    value={
                        "event": "memory",
                        "data": {
                            "id": 7,
                            "payload": {
                                "run_id": 42,
                                "content": "User prefers concise answers.",
                            },
                        },
                    },
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
)

SESSION_LIST_GET = dict(
    summary="List sessions",
    description=(
        "Returns a paginated, filterable, orderable list of sessions. "
        "Pass `detailed=false` to get lightweight records (minimal fields + `has_output_files`). "
        "Defaults to full session detail (`detailed=true`). "
        "The `detailed=true` behaviour is deprecated and will be removed in a future version."
    ),
    parameters=[
        OpenApiParameter(
            name="detailed",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.BOOL,
            description="Whether to include all session details. Set to `false` to return only minimal fields. The `true` value is deprecated and will be removed in a future version.",
            required=False,
        ),
    ],
    responses={
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
)

SESSION_RETRIEVE_GET = dict(
    summary="Retrieve a session",
    description="Returns full details of a single session by its ID.",
    responses={
        200: SessionSerializer,
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
)

SESSION_DESTROY_DELETE = dict(
    summary="Delete a session",
    description="Permanently deletes a single session by its ID.",
    responses={
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
)

SESSION_STATUSES_GET = dict(
    summary="Get session status counts grouped by graph",
    description=(
        "Returns a mapping of `graph_id` to an object of status → count pairs "
        "for all sessions matching the current filter parameters."
    ),
    responses={
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
)

SESSION_BULK_DELETE_POST = dict(
    summary="Bulk delete sessions",
    description="Deletes multiple sessions in a single atomic transaction. Returns the count and IDs of deleted sessions.",
    request=inline_serializer(
        name="SessionBulkDeleteRequest",
        fields={
            "ids": drf_serializers.ListField(child=drf_serializers.IntegerField()),
        },
    ),
    responses={
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
)

SESSION_WARNINGS_GET = dict(
    summary="Get session warnings",
    description="Returns warning messages recorded for a session, if any.",
    responses={
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
)

STOP_SESSION_POST = dict(
    summary="Stop a running session",
    description="Sends a stop signal to the session identified by its session ID. The signal must be received by all required listeners (manager and crew); if fewer than expected acknowledge, the session is marked as errored.",
    responses={
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
            description="Session not found or session ID missing.",
            examples=[
                OpenApiExample(
                    "Session ID missing",
                    value="Session id is missing",
                    response_only=True,
                    status_codes=["404"],
                ),
                OpenApiExample(
                    "Session not found",
                    value="Session not found",
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
)

GET_UPDATES_GET = dict(
    summary="Get session status update",
    description="Returns the current status of a session identified by its session ID.",
    responses={
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
            description="Session not found or session ID missing.",
            examples=[
                OpenApiExample(
                    "Session ID missing",
                    value="Session id not found",
                    response_only=True,
                    status_codes=["404"],
                ),
                OpenApiExample(
                    "Session not found",
                    value="Session not found",
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
    },
)

SESSION_OUTPUT_FILES_GET = dict(
    summary="List session output files",
    description=(
        "Returns all storage files recorded as output during the given session, "
        "ordered by the time they were added."
    ),
    responses={
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
)
