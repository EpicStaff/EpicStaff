from rest_framework import serializers

from tables.models import Graph, SubGraphNode
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin


class SubgraphNodeImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), write_only=True)

    class Meta:
        model = SubGraphNode
        exclude = ["created_at", "updated_at"]
