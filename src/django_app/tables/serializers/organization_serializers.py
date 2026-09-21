from rest_framework import serializers
from tables.models.rbac_models import Organization, User


class OrganizationCreateRequestSerializer(serializers.Serializer):
    """Schema-only — real validation in OrganizationValidationService."""

    name = serializers.CharField(max_length=255)


class OrganizationRenameRequestSerializer(serializers.Serializer):
    """Schema-only — real validation in OrganizationValidationService."""

    name = serializers.CharField(max_length=255)


class OrganizationResponseSerializer(serializers.ModelSerializer):
    """Response shape for every Organization endpoint (list, create, rename,
    deactivate, reactivate). `member_count` is supplied by the queryset
    annotation in OrganizationManagementService.
    """

    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "is_active",
            "member_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class OrganizationAdminUserSerializer(serializers.ModelSerializer):
    """User shape embedded under `admins` in the organizations list response.

    `avatar_url` is built by DRF's ImageField when `request` is in the
    serializer context, matching the convention used by /api/profile/.
    """

    avatar_url = serializers.ImageField(source="avatar", use_url=True, read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "display_name", "avatar_url"]
        read_only_fields = fields


class OrganizationListResponseSerializer(OrganizationResponseSerializer):
    """Response shape for GET /api/admin/organizations/ only.

    Adds `admins`: serialized from the `admins` attribute that
    `OrganizationManagementService.list_organizations_with_admins` attaches
    to each Organization instance (fallback already resolved by the
    service)."""

    admins = OrganizationAdminUserSerializer(many=True, read_only=True)

    class Meta(OrganizationResponseSerializer.Meta):
        fields = [*OrganizationResponseSerializer.Meta.fields, "admins"]
        read_only_fields = fields
