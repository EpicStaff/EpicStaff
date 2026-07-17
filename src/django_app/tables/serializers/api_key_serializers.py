from django.contrib.auth import get_user_model
from rest_framework import serializers

from tables.models.rbac_models import ApiKey


class ApiKeySerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)

    class Meta:
        model = ApiKey
        fields = [
            "id",
            "name",
            "prefix",
            "created_at",
            "expires_at",
            "last_used_at",
            "revoked_at",
            "status",
        ]


class ApiKeyCreateRequestSerializer(serializers.Serializer):
    # Schema-only: request validation is performed by
    # `ApiKeyValidationService.validate_create` so errors can be
    # aggregated and formatted uniformly.
    name = serializers.CharField(max_length=255)
    expires_in_days = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=3650,
        help_text="Omit for the 90-day default; null for a non-expiring key.",
    )


class ApiKeyCreateResponseSerializer(ApiKeySerializer):
    api_key = serializers.CharField(
        read_only=True,
        help_text="The raw key. Shown only in this response — it cannot be retrieved again.",
    )

    class Meta(ApiKeySerializer.Meta):
        fields = ApiKeySerializer.Meta.fields + ["api_key"]


class ApiKeyOwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ["id", "email", "display_name"]


class ApiKeyAdminSerializer(ApiKeySerializer):
    owner = ApiKeyOwnerSerializer(source="created_by", read_only=True)

    class Meta(ApiKeySerializer.Meta):
        fields = ApiKeySerializer.Meta.fields + ["owner"]
