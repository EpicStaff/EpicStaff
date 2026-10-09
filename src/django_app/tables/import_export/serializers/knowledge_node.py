from rest_framework import serializers

from tables.models import Graph, KnowledgeNode
from tables.models.base_models import SOFT_DELETE_FIELD_NAMES
from tables.models.knowledge_models import (
    KnowledgeNodeGraphRagBasicSearchConfig,
    KnowledgeNodeGraphRagDriftSearchConfig,
    KnowledgeNodeGraphRagGlobalSearchConfig,
    KnowledgeNodeGraphRagLocalSearchConfig,
    KnowledgeNodeNaiveRagSearchConfig,
)
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin


class _NaiveSearchConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeNodeNaiveRagSearchConfig
        exclude = ["id", "knowledge_node", *SOFT_DELETE_FIELD_NAMES]


class _GraphBasicSearchConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeNodeGraphRagBasicSearchConfig
        exclude = ["id", "knowledge_node", *SOFT_DELETE_FIELD_NAMES]


class _GraphLocalSearchConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeNodeGraphRagLocalSearchConfig
        exclude = ["id", "knowledge_node", *SOFT_DELETE_FIELD_NAMES]


class _GraphGlobalSearchConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeNodeGraphRagGlobalSearchConfig
        exclude = ["id", "knowledge_node", *SOFT_DELETE_FIELD_NAMES]


class _GraphDriftSearchConfigImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeNodeGraphRagDriftSearchConfig
        exclude = ["id", "knowledge_node", *SOFT_DELETE_FIELD_NAMES]


class KnowledgeNodeImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), write_only=True)
    naive_search_config = _NaiveSearchConfigImportSerializer(read_only=True)
    graph_basic_search_config = _GraphBasicSearchConfigImportSerializer(read_only=True)
    graph_local_search_config = _GraphLocalSearchConfigImportSerializer(read_only=True)
    graph_global_search_config = _GraphGlobalSearchConfigImportSerializer(read_only=True)
    graph_drift_search_config = _GraphDriftSearchConfigImportSerializer(read_only=True)

    class Meta:
        model = KnowledgeNode
        exclude = ["created_at", "updated_at"]
