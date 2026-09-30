from rest_framework import serializers
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeTool
from tables.models.python_models import PythonCodeToolConfig
from tables.models import PythonCode
from tables.models.session_models import Session
from tables.import_export.services.partial_export_service import (
    LIST_KEY_TO_ENTITY_TYPE,
)
from tables.models.rbac_models.rbac_enums import ResourceType
from tables.services.delete_services.usage import RefKind, SkipReason


class ToolUsageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    agent_surface_count = serializers.IntegerField()
    shared_surface_count = serializers.IntegerField()
    inline_surface_count = serializers.IntegerField()
    is_built_in = serializers.BooleanField()


class ToolUsageSurfaceEntrySerializer(serializers.Serializer):
    """Shared `{id, name, node_id}` shape reused for all three usage-detail
    lists — list membership (agent_surface/shared_surface/inline_surface) already
    conveys what a `kind` discriminator used to.

    `id` is a navigation target, not a unique row key: for `agent_surface`/
    `shared_surface` it's the catalog `Surface` id (unique per entry); for
    `inline_surface` it's the owning graph's id, which two different nodes in the
    same graph can share. `node_id` disambiguates that case — the id of the
    `TaskNode`/`AgentNode` the inline attachment lives on — and is always
    `null` for `agent_surface`/`shared_surface` entries, which have no node.
    """

    id = serializers.IntegerField()
    name = serializers.CharField()
    node_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class ToolUsageDetailSerializer(serializers.Serializer):
    agent_surface = ToolUsageSurfaceEntrySerializer(many=True)
    shared_surface = ToolUsageSurfaceEntrySerializer(many=True)
    inline_surface = ToolUsageSurfaceEntrySerializer(many=True)


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


class NotifyEmailSerializer(serializers.Serializer):
    to = serializers.EmailField(required=True)
    subject = serializers.CharField(
        required=False, default="EpicStaff notification", max_length=200
    )
    message = serializers.CharField(required=True, max_length=1000)


class InitRealtimeSerializer(serializers.Serializer):
    agent_definition_id = serializers.IntegerField(required=True)
    config = serializers.DictField(required=False, default=dict)


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
    document_config_ids = serializers.ListField(child=serializers.IntegerField(min_value=1))


class BulkExportSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        help_text="List of entity IDs",
    )


class BulkDeleteRequestSerializer(serializers.Serializer):
    """Request body for every bulk-delete action (BulkDeleteActionMixin).

    The algorithm is shared through BaseDeleteService; each entity declares only
    its deletable scope and its referencing sources. `dry_run` is not part of the
    body — it selects the operation, so it travels as a query parameter
    (BulkDeleteQuerySerializer).
    """

    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=500,
        help_text="List of entity IDs to delete",
    )

    def to_internal_value(self, data):
        """Reject an oversized `ids` list before validating any of its items.

        ListField validates every item first and applies `max_length` after, so
        an oversized list of junk would come back as one error per item.
        """
        ids = data.get("ids") if isinstance(data, dict) else None
        ids_field = self.fields["ids"]
        if isinstance(ids, list) and len(ids) > ids_field.max_length:
            message = ids_field.error_messages["max_length"].format(
                max_length=ids_field.max_length
            )
            raise serializers.ValidationError({"ids": [message]})
        return super().to_internal_value(data)


class BulkDeleteQuerySerializer(serializers.Serializer):
    """Query-string modifiers for the bulk-delete actions.

    A DRF BooleanField rather than a truthiness check on the raw string: a
    malformed `dry_run` must be a 400, never silently read as `False` — that
    would turn a mistyped preview into a real deletion of up to 500 rows.
    `to_internal_value` closes the two ways DRF would otherwise read it as
    `False`: a blank value (`?dry_run`, `?dry_run=`) and a repeated key.
    """

    dry_run = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Preview only: report usage and what would be deleted, "
        "without deleting anything.",
    )

    def to_internal_value(self, data):
        if hasattr(data, "getlist"):
            if len(data.getlist("dry_run")) > 1:
                raise serializers.ValidationError(
                    {"dry_run": ["Pass dry_run at most once."]}
                )
            # A QueryDict is treated as HTML form input, where a blank optional
            # value counts as absent and falls back to the default. A plain dict
            # hands the blank to BooleanField, which rejects it.
            data = data.dict()
        return super().to_internal_value(data)


class UsageRefSerializer(serializers.Serializer):
    resource_type = serializers.ChoiceField(choices=ResourceType.choices)
    kind = serializers.ChoiceField(choices=RefKind.choices)
    id = serializers.IntegerField()
    name = serializers.CharField(allow_null=True)


class UsageBucketSerializer(serializers.Serializer):
    """One resource type's references. The hidden total never reaches the wire."""

    resource_type = serializers.ChoiceField(choices=ResourceType.choices)
    visible_count = serializers.IntegerField()
    visible_sample = UsageRefSerializer(many=True)
    truncated = serializers.BooleanField()


class UsageReportSerializer(serializers.Serializer):
    blocked = serializers.BooleanField()
    by_resource_type = UsageBucketSerializer(many=True, source="buckets")


class SkippedEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    reason = serializers.ChoiceField(choices=SkipReason.choices)


class BulkDeleteResultSerializer(serializers.Serializer):
    """The response of every bulk-delete action, for every entity.

    `usage` is keyed by entity id; JSON object keys are always strings, so those
    keys arrive as strings while every other id field is an integer. `usage` is
    populated on a dry run only — a real delete returns `{}`, keeping the key
    present so the shape never varies.
    """

    dry_run = serializers.BooleanField()
    deleted_count = serializers.IntegerField()
    deleted_ids = serializers.ListField(child=serializers.IntegerField())
    deletable_ids = serializers.ListField(child=serializers.IntegerField())
    not_found_ids = serializers.ListField(child=serializers.IntegerField())
    skipped = SkippedEntrySerializer(many=True)
    usage = serializers.DictField(child=UsageReportSerializer())


class GraphNodesPartialExportSerializer(serializers.Serializer):
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
    knowledge_node_list = serializers.ListField(
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


class InspectImportRequestSerializer(serializers.Serializer):
    file = serializers.FileField()


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
