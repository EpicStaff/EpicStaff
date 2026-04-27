from rest_framework import serializers

from tables.models import Graph, GraphVersion


class GraphVersionCreateSerializer(serializers.Serializer):
    graph_id = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), source="graph"
    )
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, default="", allow_blank=True)


class GraphVersionReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphVersion
        fields = [
            "id",
            "graph_id",
            "name",
            "description",
            "created_at",
        ]
