from rest_framework import serializers
from tables.models.mcp_models import McpTool
from tables.models.crew_models import ToolConfig
from tables.models.python_models import PythonCodeTool
from tables.models.python_models import PythonCodeToolConfig


class RunSessionSerializer(serializers.Serializer):
    graph_id = serializers.IntegerField(required=False)
    graph_uuid = serializers.UUIDField(required=False)
    variables = serializers.JSONField(required=False)
    files = serializers.DictField(
        child=serializers.CharField(), required=False, allow_null=True, default=dict
    )
    username = serializers.CharField(required=False)

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


class EnvironmentConfigSerializer(serializers.Serializer):
    data = serializers.DictField(required=True)


class InitRealtimeSerializer(serializers.Serializer):
    agent_id = serializers.IntegerField(required=True)
    config = serializers.DictField(required=False, default=dict)


class BaseToolSerializer(serializers.Serializer):
    unique_name = serializers.CharField(required=True)  # type + id
    data = serializers.DictField(required=True)

    def to_representation(self, instance):  # instance is a Tool instance
        from tables.serializers.model_serializers import (
            PythonCodeToolSerializer,
            McpToolSerializer,
            ToolConfigSerializer,
            PythonCodeToolConfigSerializer,
        )

        repr = {}
        if isinstance(instance, PythonCodeTool):
            repr["unique_name"] = f"python-code-tool:{instance.pk}"
            repr["data"] = PythonCodeToolSerializer(instance).data
        elif isinstance(instance, ToolConfig):
            repr["unique_name"] = f"configured-tool:{instance.pk}"
            repr["data"] = ToolConfigSerializer(instance).data
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


class ImportRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    preserve_uuids = serializers.BooleanField(default=False, required=False)
