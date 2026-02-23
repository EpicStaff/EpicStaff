from rest_framework import serializers


class TimestampMixin(serializers.Serializer):
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        common_fields = ["created_at", "updated_at"]


class ContentHashMixin(serializers.Serializer):
    content_hash = serializers.CharField(read_only=True)

    class Meta:
        common_fields = ["content_hash"]


class MetadataMixin(serializers.Serializer):
    metadata = serializers.JSONField()

    class Meta:
        common_fields = ["metadata"]


class BaseGraphEntityMixin(TimestampMixin, ContentHashMixin, MetadataMixin):
    class Meta:
        common_fields = (
            TimestampMixin.Meta.common_fields
            + ContentHashMixin.Meta.common_fields
            + MetadataMixin.Meta.common_fields
        )
