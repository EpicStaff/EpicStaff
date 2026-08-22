from rest_framework import serializers

from tables.models import Graph, EndNode


class EndNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )

    class Meta:
        model = EndNode
        exclude = ["created_at", "updated_at"]
