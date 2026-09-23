from rest_framework import serializers
from tables.models.rbac_models.organization import Organization
from tables.models.rbac_models.organization_user import OrganizationUser


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class OrganizationUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationUser
        fields = ["id", "user", "org", "role", "joined_at"]
        read_only_fields = ["id", "joined_at"]
