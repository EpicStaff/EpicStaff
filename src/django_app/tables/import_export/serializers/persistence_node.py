from rest_framework import serializers

from tables.models import Graph, PersistenceNode


class PersistenceNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), write_only=True)
    # Exported for re-binding only; never trusted as a raw FK on import.
    persistence_table = serializers.PrimaryKeyRelatedField(read_only=True)
    persistence_table_name = serializers.SerializerMethodField()

    class Meta:
        model = PersistenceNode
        exclude = ["created_at", "updated_at"]

    def get_persistence_table_name(self, node: PersistenceNode) -> str | None:
        return node.persistence_table.name if node.persistence_table else None
