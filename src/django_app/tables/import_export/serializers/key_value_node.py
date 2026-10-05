from rest_framework import serializers

from tables.models import Graph, KeyValueNode
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin
from tables.validators.key_value_entries_validator import KeyValueEntriesValidator


class KeyValueNodeImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), write_only=True)
    # Exported for re-binding only; never trusted as a raw FK on import.
    key_value_table = serializers.PrimaryKeyRelatedField(read_only=True)
    key_value_table_name = serializers.SerializerMethodField()

    class Meta:
        model = KeyValueNode
        exclude = ["created_at", "updated_at"]

    def get_key_value_table_name(self, node: KeyValueNode) -> str | None:
        return node.key_value_table.name if node.key_value_table else None

    def validate(self, attrs):
        attrs = super().validate(attrs)
        mode = attrs.get("mode", KeyValueNode.Mode.READ)
        attrs["entries"] = KeyValueEntriesValidator().validate(mode, attrs.get("entries", []))
        return attrs
