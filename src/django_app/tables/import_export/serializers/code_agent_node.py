from rest_framework import serializers

from tables.models import Graph
from tables.models.graph_models import CodeAgentNode


class CodeAgentNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )

    class Meta:
        model = CodeAgentNode
        exclude = ["created_at", "updated_at"]
