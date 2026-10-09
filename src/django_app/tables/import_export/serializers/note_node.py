from rest_framework import serializers

from tables.models import Graph
from tables.models.graph_models import GraphNote
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin


class GraphNoteImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), write_only=True)

    class Meta:
        model = GraphNote
        exclude = ["created_at", "updated_at"]
