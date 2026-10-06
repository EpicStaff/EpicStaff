"""Response shapes of the recycle-bin endpoints."""

from rest_framework import serializers


class RecycleBinEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    deleted_at = serializers.DateTimeField()
    days_left = serializers.IntegerField()


class BinNodeSerializer(serializers.Serializer):
    # Decision-table nodes allow a blank node_name.
    name = serializers.CharField(allow_blank=True)
    node_type = serializers.CharField()


class FlowRecycleBinEntrySerializer(RecycleBinEntrySerializer):
    nodes = BinNodeSerializer(many=True)


class RestoreResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    renamed_from = serializers.CharField(allow_null=True)


class RecycleBinSettingsSerializer(serializers.Serializer):
    retention_days = serializers.IntegerField()
