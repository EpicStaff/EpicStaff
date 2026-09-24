from rest_framework import serializers
from tables.constants.persistence_constants import (
    MAX_KEY_LENGTH,
    MAX_KEYS_PER_REQUEST,
    MAX_TABLE_NAME_LENGTH,
)
from tables.models import PersistenceTable, PersistenceTableEntry
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)
from tables.services.persistence_table_service import PersistenceTableService


class PersistenceTableSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=MAX_TABLE_NAME_LENGTH,
        validators=[
            OrgScopedUniqueValidator(
                queryset=PersistenceTable.objects.all(),
                lookup="iexact",
                message="A table with this name already exists.",
            )
        ],
    )
    entry_count = serializers.SerializerMethodField()

    class Meta:
        model = PersistenceTable
        fields = ["id", "name", "description", "entry_count", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def get_entry_count(self, table: PersistenceTable) -> int:
        return getattr(table, "entry_count", 0)


class PersistenceTableEntrySerializer(serializers.ModelSerializer):
    table = OrgScopedPrimaryKeyRelatedField(queryset=PersistenceTable.objects.all())
    key = serializers.CharField(max_length=MAX_KEY_LENGTH, trim_whitespace=False)
    value = serializers.JSONField(allow_null=True)
    updated_by_graph = serializers.IntegerField(
        source="updated_by_session.graph_id", read_only=True, allow_null=True
    )

    class Meta:
        model = PersistenceTableEntry
        fields = [
            "id",
            "table",
            "key",
            "value",
            "created_at",
            "updated_at",
            "updated_by_session",
            "updated_by_graph",
        ]
        read_only_fields = ["created_at", "updated_at", "updated_by_session"]

    def validate_key(self, key: str) -> str:
        PersistenceTableService().validate_key(key)
        return key

    def validate_value(self, value):
        PersistenceTableService().validate_value(value)
        return value


class PersistenceKeysSerializer(serializers.Serializer):
    keys = serializers.ListField(
        child=serializers.CharField(max_length=MAX_KEY_LENGTH, trim_whitespace=False),
        max_length=MAX_KEYS_PER_REQUEST,
    )


class PersistenceWriteSerializer(serializers.Serializer):
    entries = serializers.DictField(child=serializers.JSONField(allow_null=True))

    def validate_entries(self, entries: dict) -> dict:
        if len(entries) > MAX_KEYS_PER_REQUEST:
            raise serializers.ValidationError(
                f"At most {MAX_KEYS_PER_REQUEST} entries per request."
            )
        return entries
