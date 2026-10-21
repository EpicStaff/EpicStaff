from django.contrib.auth import get_user_model
from rest_framework import serializers

from rbac.models import ApiKey
from rbac.profile.avatar import build_avatar_url


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
        fields = [*ApiKeySerializer.Meta.fields, "api_key"]


class ApiKeyOwnerSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = ["id", "email", "display_name", "avatar_url"]

    def get_avatar_url(self, user) -> str | None:
        return build_avatar_url(user)


class ApiKeyAdminSerializer(ApiKeySerializer):
    owner = ApiKeyOwnerSerializer(source="created_by", read_only=True)
    org_ids = serializers.SerializerMethodField()

    class Meta(ApiKeySerializer.Meta):
        fields = [*ApiKeySerializer.Meta.fields, "owner", "org_ids"]

    def get_org_ids(self, key: ApiKey) -> list[int]:
        """Set by ApiKeyManagementService.attach_visible_orgs."""
        return getattr(key, "_visible_org_ids", [])
