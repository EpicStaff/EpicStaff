from urllib.parse import urlsplit

from django.conf import settings
from rbac.models.enums import ResourceType
from rest_framework import serializers
from tables.import_export.services.partial_export_service import (
    LIST_KEY_TO_ENTITY_TYPE,
)
from tables.models import PythonCode
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeTool, PythonCodeToolConfig
from tables.models.session_models import Session
from tables.serializers.naive_rag_serializers import DocumentConfigEstimateOverrideSerializer
from tables.serializers.utils.list_fields import BoundedListField
from tables.services.code_run_targets import CODE_RUN_TARGETS
from tables.services.delete_services.usage import SkipReason
from tables.services.trigger_test_run.registry import TEST_RUN_STRATEGIES
from tables.validators.trigger_payload_validator import validate_trigger_payload


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
    # Deliberately unvalidated passthrough -- whatever the caller nests in here
    # (e.g. a client-supplied context.chat_history, including fabricated
    # assistant turns) rides through untouched. Closed as Won't Fix: today only
    # the EpicChat widget's chatMessage key is actually read downstream, so a
    # visitor editing their own browser storage only rewrites their own
    # conversation context. That is a fact about today's flow configuration,
    # not a guarantee this field enforces -- nothing here rejects chat_history,
    # it is simply unused. Re-read this decision before ever adding a flow or
    # tool that reads chat_history (or any other key under this blob) as trusted
    # prior-turn history, authorization, or a stored record.
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
    token_budget = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    # Delivered by the session callback sender once the run reaches a terminal
    # status. Only the system API key may set these (the view enforces it); the
    # host must be on SESSION_CALLBACK_ALLOWED_HOSTS so the sender cannot be
    # aimed at an internal service.
    # CharField, not URLField: URLField rejects single-label hosts such as `chat`,
    # which is how compose services are addressed; the allowlist below is the guard.
    callback_url = serializers.CharField(required=False, allow_null=True, max_length=2048)
    callback_secret = serializers.CharField(
        required=False, allow_null=True, min_length=32, max_length=256, trim_whitespace=False
    )

    def validate_callback_url(self, value):
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https"):
            raise serializers.ValidationError("Enter a valid http(s) URL.")
        try:
            parts.port  # noqa: B018 -- reading it is the validation
        except ValueError:
            raise serializers.ValidationError("Invalid port in callback URL.") from None
        host = (parts.hostname or "").lower()
        if host not in settings.SESSION_CALLBACK_ALLOWED_HOSTS:
            raise serializers.ValidationError("Host is not an allowed callback target.")
        return value

    def validate(self, attrs):
        if not attrs.get("graph_id") and not attrs.get("graph_uuid"):
            raise serializers.ValidationError("Either 'graph_id' or 'graph_uuid' must be provided.")
        if (attrs.get("callback_url") is None) != (attrs.get("callback_secret") is None):
            raise serializers.ValidationError(
                {"callback_secret": "callback_url and callback_secret must be given together."}
            )
        return attrs


class SessionTestRunSerializer(serializers.Serializer):
    graph_id = serializers.IntegerField()
    node_type = serializers.ChoiceField(choices=sorted(TEST_RUN_STRATEGIES))
    node_id = serializers.IntegerField()
    payload = serializers.JSONField(validators=[validate_trigger_payload])


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
            McpToolSerializer,
            PythonCodeToolConfigSerializer,
            PythonCodeToolSerializer,
        )

        repr = {}
        if isinstance(instance, PythonCodeTool):
            repr["unique_name"] = f"python-code-tool:{instance.pk}"
            repr["data"] = PythonCodeToolSerializer(instance, context=self.context).data
        elif isinstance(instance, McpTool):
            repr["unique_name"] = f"mcp-tool:{instance.pk}"
            repr["data"] = McpToolSerializer(instance, context=self.context).data
        elif isinstance(instance, PythonCodeToolConfig):
            repr["unique_name"] = f"python-code-tool-config:{instance.pk}"
            repr["data"] = PythonCodeToolConfigSerializer(instance, context=self.context).data
        else:
            raise TypeError(f"Unsupported tool type for serialization: {type(instance)}")

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


class ProcessRagIndexingEstimateSerializer(ProcessRagIndexingSerializer):
    """Estimate request: the indexing body plus optional unsaved per-document chunking settings."""

    document_configs = DocumentConfigEstimateOverrideSerializer(
        many=True, required=False, default=list
    )

    def validate_document_configs(self, document_configs):
        config_ids = [item["document_config_id"] for item in document_configs]
        if len(config_ids) != len(set(config_ids)):
            raise serializers.ValidationError("document_config_id must be unique.")
        return document_configs

    def validate(self, attrs):
        extra_ids = {item["document_config_id"] for item in attrs["document_configs"]} - set(
            attrs["document_config_ids"]
        )
        if extra_ids:
            raise serializers.ValidationError(
                {
                    "document_configs": (
                        f"document_config_id not in document_config_ids: {sorted(extra_ids)}"
                    )
                }
            )
        return attrs


class BulkExportSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        help_text="List of entity IDs",
    )

    def validate_ids(self, ids: list[int]) -> list[int]:
        # Callers compare the number of rows found against len(ids), so a
        # repeated id would otherwise be reported as a missing entity.
        return list(dict.fromkeys(ids))


class BulkDeleteQuerySerializer(serializers.Serializer):
    dry_run = serializers.BooleanField(
        default=False,
        help_text=(
            "Preview only: report what would be deleted and the usage that blocks "
            "the rest, without deleting anything. A preview always responds 200. "
            "This is a query parameter: a `dry_run` field in the request body is "
            "ignored and the call runs as a real delete."
        ),
    )


class BulkDeleteRequestSerializer(serializers.Serializer):
    ids = BoundedListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=500,
        help_text="List of entity IDs to delete",
    )


class UsageRefSerializer(serializers.Serializer):
    resource_type = serializers.ChoiceField(choices=ResourceType.choices)
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
    """Response of every bulk-delete action.

    `usage` is keyed by entity id (strings, as JSON keys) and is filled on a dry
    run only; a real delete returns `{}`.
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
    key_value_node_list = serializers.ListField(
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
    id_search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Keep sessions whose id contains this value (`12` matches 12, 112, 1203). "
            "Blank means no filtering; a value with non-digits matches nothing."
        ),
    )
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
                {"replace_existing": "replace_existing=True requires preserve_uuids=True."}
            )
        return attrs


class InspectImportRequestSerializer(serializers.Serializer):
    file = serializers.FileField()


class CodeRunTargetSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=sorted(CODE_RUN_TARGETS))
    id = serializers.IntegerField(min_value=1)


class RunPythonCodeSerializer(serializers.Serializer):
    """Exactly one of `target` (a code slot of a node, run as a real run would)
    or `python_code_id` (the bare code, without the node's storage)."""

    python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="python_code",
        required=False,
    )
    target = CodeRunTargetSerializer(required=False)
    variables = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        default=dict,
    )

    def validate(self, attrs):
        if ("target" in attrs) == ("python_code" in attrs):
            raise serializers.ValidationError(
                "Provide exactly one of `target` or `python_code_id`."
            )
        return attrs
