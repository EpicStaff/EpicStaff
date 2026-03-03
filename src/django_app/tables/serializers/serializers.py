from django.db import models
from django.conf import settings
from rest_framework import serializers
from tables.models.mcp_models import McpTool
from tables.models.crew_models import ToolConfig
from tables.models.python_models import PythonCodeTool
from tables.models.graph_models import GraphFile, Graph
from tables.models.python_models import PythonCodeToolConfig


class RunSessionSerializer(serializers.Serializer):
    graph_id = serializers.IntegerField(required=True)
    variables = serializers.JSONField(required=False)
    files = serializers.DictField(
        child=serializers.CharField(), required=False, allow_null=True, default=dict
    )
    username = serializers.CharField(required=False)


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


class UploadGraphFileSerializer(serializers.Serializer):
    files = serializers.DictField(
        child=serializers.FileField(), allow_empty=False, write_only=True
    )
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all())

    def create(self, validated_data):
        files = validated_data.pop("files")
        graph = validated_data.get("graph")

        instances = []
        for key, file in files.items():
            instance = GraphFile.objects.create(
                graph=graph,
                file=file,
                domain_key=key,
                name=file.name,
                size=file.size,
                content_type=getattr(file, "content_type", ""),
            )
            instances.append(instance)

        return instances

    def validate(self, attrs):
        graph = attrs.get("graph")
        files = attrs.get("files")

        if not graph:
            raise serializers.ValidationError({"graph": "Graph ID is required."})

        domain_keys = list(files.keys())
        if GraphFile.objects.filter(graph=graph, domain_key__in=domain_keys).exists():
            raise serializers.ValidationError(
                {"files": "One or more domain_key(s) already exist for this graph."}
            )

        current_total = (
            GraphFile.objects.filter(graph=graph).aggregate(total=models.Sum("size"))[
                "total"
            ]
            or 0
        )

        new_files_size = sum(file.size for file in files.values())
        total_size = current_total + new_files_size
        max_mb = round(settings.MAX_TOTAL_FILE_SIZE / 1024 / 1024, 2)
        total_mb = round(total_size / 1024 / 1024, 2)

        if total_mb > max_mb:
            raise serializers.ValidationError(
                {
                    "files": f"Total file size for this graph would exceed {max_mb:.2f}MB. "
                    f"Current: {current_total / (1024 * 1024):.2f}MB, "
                    f"New files: {new_files_size / (1024 * 1024):.2f}MB, "
                    f"Total would be: {total_size / (1024 * 1024):.2f}MB"
                }
            )

        return attrs


class GraphFileUpdateSerializer(serializers.Serializer):
    domain_key = serializers.CharField()
    file = serializers.FileField()

    def validate_domain_key(self, value):
        graph = self.context.get("graph")
        if not graph:
            raise serializers.ValidationError("Graph context is required.")
        return value

    def update(self, instance, validated_data):
        new_file = validated_data.get("file")
        if new_file:
            instance.file = new_file
            instance.name = new_file.name
            instance.size = new_file.size
            instance.content_type = getattr(new_file, "content_type", "")

        new_domain_key = validated_data.get("domain_key")
        if new_domain_key and new_domain_key != instance.domain_key:
            graph = instance.graph
            if (
                GraphFile.objects.filter(graph=graph, domain_key=new_domain_key)
                .exclude(id=instance.id)
                .exists()
            ):
                raise serializers.ValidationError(
                    {
                        "domain_key": f"Domain key '{new_domain_key}' already exists for this graph."
                    }
                )
            instance.domain_key = new_domain_key

        instance.save()
        return instance


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
