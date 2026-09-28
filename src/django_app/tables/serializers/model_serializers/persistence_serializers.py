from rbac.scoping.fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)
from rest_framework import serializers
from tables.constants.persistence_constants import (
    MAX_KEY_LENGTH,
    MAX_KEYS_PER_REQUEST,
    MAX_TABLE_NAME_LENGTH,
)
from tables.models import PersistenceTable, PersistenceTableEntry
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
    # Both read annotations from PersistenceTableEntryViewSet's queryset, so listing
    # entries never loads the session or graph rows. Only the internal run route sets
    # `updated_by_session`, and it accepts only tables in the session flow's org, so the
    # name never comes from another org.
    updated_by_graph = serializers.IntegerField(
        source="updated_by_graph_id", read_only=True, allow_null=True
    )
    updated_by_graph_name = serializers.CharField(read_only=True, allow_null=True)

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
            "updated_by_graph_name",
        ]
        read_only_fields = ["created_at", "updated_at", "updated_by_session"]
        # The (table, key) check in `validate` replaces DRF's generated one, which reports a
        # duplicate as a non-field error.
        validators = []

    def validate_table(self, table: PersistenceTable) -> PersistenceTable:
        if self.instance is not None and table.pk != self.instance.table_id:
            raise serializers.ValidationError("An entry can't be moved to another table.")
        return table

    def validate_key(self, key: str) -> str:
        PersistenceTableService().validate_key(key)
        return key

    def validate_value(self, value):
        PersistenceTableService().validate_value(value)
        return value

    # NOTE: two concurrent renames onto the same key can both pass this check; the second
    # then hits the DB constraint and surfaces as an IntegrityError (500), the same race
    # DRF's generated UniqueTogetherValidator has.
    def validate(self, attrs: dict) -> dict:
        # An entry can't change table, so without a new key there is nothing to collide with.
        if "key" not in attrs:
            return attrs
        table_id = attrs["table"].pk if "table" in attrs else self.instance.table_id
        duplicates = PersistenceTableEntry.objects.filter(table_id=table_id, key=attrs["key"])
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError(
                {"key": "An entry with this key already exists in this table."}, code="unique"
            )
        return attrs


class PersistenceTableEntryListSerializer(PersistenceTableEntrySerializer):
    """A list row: `value` (up to 256 KiB) swapped for a preview of its JSON text.

    Reads the `value_preview` / `value_truncated` annotations that
    PersistenceTableService.with_value_preview adds; the full value is on the detail route.
    """

    value = None
    value_preview = serializers.CharField(read_only=True)
    value_truncated = serializers.BooleanField(read_only=True)

    class Meta(PersistenceTableEntrySerializer.Meta):
        fields = [
            "id",
            "table",
            "key",
            "value_preview",
            "value_truncated",
            "created_at",
            "updated_at",
            "updated_by_session",
            "updated_by_graph",
            "updated_by_graph_name",
        ]


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
