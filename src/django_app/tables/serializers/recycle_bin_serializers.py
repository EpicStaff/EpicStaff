"""Response shapes of the recycle-bin endpoints."""

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


class BinDetailSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.JSONField(
        allow_null=True,
        help_text="Text, an ISO 8601 date or a size in bytes, per `format`; null when the field is empty",
    )
    format = serializers.ChoiceField(
        choices=["text", "date", "size", "notice"],
        help_text="How to show `value`; `notice` is text the UI highlights",
    )


class RecycleBinEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    deleted_at = serializers.DateTimeField()
    days_left = serializers.IntegerField()
    details = BinDetailSerializer(
        many=True, help_text="Basic info about the item; empty values are left out"
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
