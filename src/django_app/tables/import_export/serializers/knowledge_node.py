from rest_framework import serializers

from tables.models import Graph, KnowledgeNode
from tables.models.knowledge_models import (
    KnowledgeNodeGraphRagBasicSearchConfig,
    KnowledgeNodeGraphRagLocalSearchConfig,
    KnowledgeNodeNaiveRagSearchConfig,
)


class _NaiveSearchConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeNodeNaiveRagSearchConfig
        exclude = ["id", "knowledge_node"]


class _GraphBasicSearchConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeNodeGraphRagBasicSearchConfig
        exclude = ["id", "knowledge_node"]


class _GraphLocalSearchConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeNodeGraphRagLocalSearchConfig
        exclude = ["id", "knowledge_node"]


class KnowledgeNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )
    naive_search_config = _NaiveSearchConfigImportSerializer(read_only=True)
    graph_basic_search_config = _GraphBasicSearchConfigImportSerializer(read_only=True)
    graph_local_search_config = _GraphLocalSearchConfigImportSerializer(read_only=True)

    class Meta:
        model = KnowledgeNode
        exclude = ["created_at", "updated_at"]
