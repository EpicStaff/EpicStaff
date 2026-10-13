"""Response shapes of the recycle-bin endpoints."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


class BinContentSerializer(serializers.Serializer):
    # Decision-table nodes allow a blank node_name.
    name = serializers.CharField(allow_blank=True)
    kind = serializers.CharField(
        help_text="A frontend NodeType value for flow nodes; otherwise surface, python_tool, mcp_tool, "
        "knowledge_source, file, folder or document."
    )


class RecycleBinContentsSerializer(serializers.Serializer):
    """One binned item's contents for "Show all": up to 5,000 (the list sends at most 100).

    `contents_total` is the full count, so a longer list can say how many more there are.
    """

    contents = BinContentSerializer(many=True)
    contents_total = serializers.IntegerField()


# The user summary every authorship field renders (rbac UserSummarySerializer).
_USER_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "display_name": {"type": "string", "nullable": True},
        "avatar_url": {"type": "string", "nullable": True},
    },
    "required": ["id", "display_name", "avatar_url"],
}


@extend_schema_field(
    {
        "oneOf": [{"type": "string"}, {"type": "integer"}, _USER_SUMMARY_SCHEMA],
        "nullable": True,
    }
)
class BinDetailValueField(serializers.JSONField):
    """A detail's value: text, a date, a size or a user summary, per the detail's `format`."""


class BinDetailSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = BinDetailValueField(
        allow_null=True,
        help_text="Text (`text`, `notice`), an ISO 8601 date (`date`), a size in bytes (`size`) "
        "or a user summary {id, display_name, avatar_url} (`user`); null when the field is "
        "empty or, for `user`, the user is unknown",
    )
    format = serializers.ChoiceField(
        choices=["text", "date", "size", "notice", "user"],
        help_text="How to show `value`; `notice` is text the UI highlights",
    )


class RecycleBinEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    deleted_at = serializers.DateTimeField()
    days_left = serializers.IntegerField()
    details = BinDetailSerializer(
        many=True,
        help_text='Basic info about the item: always "Created by" and "Deleted by" first '
        "(format `user`), then the tab's fields. Every line is sent, null when empty",
    )
    contents = BinContentSerializer(
        many=True, help_text="What a restore brings back with it (at most 100)"
    )
    contents_total = serializers.IntegerField(
        help_text="How many items a restore brings back with it in all"
    )


class RestoreResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    renamed_from = serializers.CharField(allow_null=True)
    links_restored = serializers.BooleanField(
        help_text="True when what used the item is connected to it again (it kept its links "
        "in the bin); false when the links were removed on delete and don't come back"
    )


class RecycleBinSettingsSerializer(serializers.Serializer):
    retention_days = serializers.IntegerField()


class RecycleBinBulkRequestSerializer(serializers.Serializer):
    """Either the selected `ids` or `all: true` for every item in the bin."""

    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=100, required=False
    )
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if bool(attrs.get("ids")) == attrs["all"]:
            raise serializers.ValidationError("Send either `ids` or `all: true`.")
        return attrs


class RecycleBinBulkFailureSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    message = serializers.CharField()


class RecycleBinBulkRestoreResponseSerializer(serializers.Serializer):
    restored = RestoreResultSerializer(many=True)
    failed = RecycleBinBulkFailureSerializer(many=True)


class RecycleBinBulkPurgeResponseSerializer(serializers.Serializer):
    purged = serializers.ListField(child=serializers.IntegerField())
    failed = RecycleBinBulkFailureSerializer(many=True)


class RecycleBinEmptyFailureSerializer(RecycleBinBulkFailureSerializer):
    source = serializers.CharField(help_text="The bin the item was in, e.g. `flow` or `secret`.")


class RecycleBinEmptyResponseSerializer(serializers.Serializer):
    purged_count = serializers.IntegerField(help_text="How many items were deleted for good.")
    failed = RecycleBinEmptyFailureSerializer(many=True)
    remaining = serializers.IntegerField(
        help_text=(
            "Items still in those bins: call again while it goes down. One call purges for "
            "a limited time, so a large bin takes several."
        )
    )
