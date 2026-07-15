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


class ApiKeyOwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ["id", "email", "display_name"]


class ApiKeyAdminSerializer(ApiKeySerializer):
    owner = ApiKeyOwnerSerializer(source="created_by", read_only=True)

    class Meta(ApiKeySerializer.Meta):
        fields = ApiKeySerializer.Meta.fields + ["owner"]
