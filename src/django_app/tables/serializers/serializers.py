from rest_framework import serializers
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeTool
from tables.models.python_models import PythonCodeToolConfig
from tables.models import PythonCode
from tables.models.session_models import Session
from tables.import_export.services.partial_export_service import (
    LIST_KEY_TO_ENTITY_TYPE,
)


class ToolUsageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    projects_count = serializers.IntegerField()
    staff_count = serializers.IntegerField()
    is_built_in = serializers.BooleanField()


class ToolUsageProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ToolUsageStaffSerializer(serializers.Serializer):
    # Agent has no `name` field — `role` is its display identity
    # (see tables.models.crew_models.Agent.__str__).
    id = serializers.IntegerField()
    role = serializers.CharField()


class ToolUsageDetailSerializer(serializers.Serializer):
    projects = ToolUsageProjectSerializer(many=True)
    staff = ToolUsageStaffSerializer(many=True)


class RunSessionSerializer(serializers.Serializer):
    graph_id = serializers.IntegerField(required=False)
    graph_uuid = serializers.UUIDField(required=False)
    variables = serializers.JSONField(required=False)
    files = serializers.DictField(
        child=serializers.CharField(), required=False, allow_null=True, default=dict
    )
    # Optional: links the newly created Session to a caller session via the
    # existing Session.parent_session self-FK (see migration 0162). Used by
    # the built-in "subflow_tool" so a sub-flow run is traceable back to the
    # agent session that triggered it. Not exposed by any UI form — purely a
    # programmatic/tool-runtime input.
    parent_session_id = serializers.IntegerField(required=False, allow_null=True)
    # optional run-level token budget hard stop. Not exposed
    # by any UI form. Threaded to crew via SessionData.initial_state's
    # reserved "__token_budget__" key (see
    # SessionManagerService.create_session_data) rather than a new typed
    # SessionData field. Omitted/None (default) means "no limit" -- inert
    # for every existing caller.
    token_budget = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )

    def validate(self, attrs):
        if not attrs.get("graph_id") and not attrs.get("graph_uuid"):
            raise serializers.ValidationError(
                "Either 'graph_id' or 'graph_uuid' must be provided."
            )
        return attrs


class GetUpdatesSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=True)


class AnswerToLLMSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=True)
    crew_id = serializers.IntegerField(required=True)
    execution_order = serializers.IntegerField(required=True)
    name = serializers.CharField()
    answer = serializers.CharField()


class NotifyEmailSerializer(serializers.Serializer):
    to = serializers.EmailField(required=True)
    subject = serializers.CharField(
        required=False, default="EpicStaff notification", max_length=200
    )
    message = serializers.CharField(required=True, max_length=1000)


class InitRealtimeSerializer(serializers.Serializer):
    agent_id = serializers.IntegerField(required=False)
    agent_definition_id = serializers.IntegerField(required=False)
    config = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        agent_id = attrs.get("agent_id")
        agent_definition_id = attrs.get("agent_definition_id")

        if bool(agent_id) == bool(agent_definition_id):
            raise serializers.ValidationError(
                "Exactly one of 'agent_id' or 'agent_definition_id' must be provided."
            )

        return attrs


class BaseToolSerializer(serializers.Serializer):
    unique_name = serializers.CharField(required=True)  # type + id
    data = serializers.DictField(required=True)

    def to_representation(self, instance):  # instance is a Tool instance
        from tables.serializers.model_serializers import (
            PythonCodeToolSerializer,
            McpToolSerializer,
            PythonCodeToolConfigSerializer,
        )

        repr = {}
        if isinstance(instance, PythonCodeTool):
            repr["unique_name"] = f"python-code-tool:{instance.pk}"
            repr["data"] = PythonCodeToolSerializer(instance).data
        elif isinstance(instance, McpTool):
            repr["unique_name"] = f"mcp-tool:{instance.pk}"
            repr["data"] = McpToolSerializer(instance).data
        elif isinstance(instance, PythonCodeToolConfig):
            repr["unique_name"] = f"python-code-tool-config:{instance.pk}"
            repr["data"] = PythonCodeToolConfigSerializer(instance).data
        else:
            raise TypeError(
                f"Unsupported tool type for serialization: {type(instance)}"
            )

        return repr


class RegisterTelegramTriggerSerializer(serializers.Serializer):
    telegram_trigger_node_id = serializers.IntegerField(required=True)


class ProcessDocumentChunkingSerializer(serializers.Serializer):
    document_id = serializers.IntegerField(required=True)


class ProcessCollectionEmbeddingSerializer(serializers.Serializer):
    collection_id = serializers.IntegerField(required=True)


class ProcessRagIndexingSerializer(serializers.Serializer):
    """
    Serializer for RAG indexing endpoint
    Business logic is in IndexingService
    """

    rag_id = serializers.IntegerField(required=True, min_value=1)
    rag_type = serializers.ChoiceField(required=True, choices=["naive", "graph"])


class BulkExportSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        help_text="List of entity IDs",
    )


class GraphNodesPartialExportSerializer(serializers.Serializer):
    crew_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    python_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    audio_transcription_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    file_extractor_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    subgraph_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    webhook_trigger_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    telegram_trigger_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    decision_table_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    classification_decision_table_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    graph_note_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    schedule_trigger_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    agent_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    task_node_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )
    edge_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list
    )

    def validate(self, attrs):
        if not any(attrs.get(key) for key in LIST_KEY_TO_ENTITY_TYPE):
            raise serializers.ValidationError("At least one node must be provided.")
        return attrs


class SessionExportAllSerializer(serializers.Serializer):
    graph_id = serializers.IntegerField(required=False, min_value=1)
    graph_name = serializers.CharField(required=False)
    status = serializers.ListField(
        child=serializers.ChoiceField(choices=Session.SessionStatus.choices),
        required=False,
    )
    node_name = serializers.CharField(required=False)
    is_error_cause = serializers.BooleanField(required=False)
    created_at_after = serializers.DateTimeField(required=False)
    created_at_before = serializers.DateTimeField(required=False)
    finished_at_after = serializers.DateTimeField(required=False)
    finished_at_before = serializers.DateTimeField(required=False)


class ImportRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    preserve_uuids = serializers.BooleanField(default=False, required=False)
    replace_existing = serializers.BooleanField(default=False, required=False)
    import_labels = serializers.BooleanField(default=True, required=False)

    def validate(self, attrs):
        if attrs.get("replace_existing") and not attrs.get("preserve_uuids"):
            raise serializers.ValidationError(
                {
                    "replace_existing": "replace_existing=True requires preserve_uuids=True."
                }
            )
        return attrs


class RunPythonCodeSerializer(serializers.Serializer):
    python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="python_code",
    )
    variables = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        default=dict,
    )
