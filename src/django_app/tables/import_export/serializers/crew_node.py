from rest_framework import serializers

from tables.models import Graph, CrewNode


class CrewNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )

    class Meta:
        model = CrewNode
        exclude = ["created_at", "updated_at"]
