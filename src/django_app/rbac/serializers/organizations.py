from rest_framework import serializers
from tables.models.user import User

from rbac.models import Organization, OrganizationConfig
from rbac.profile.avatar import build_avatar_url

# Product cap: 100 years. 0 = unlimited.
AUDIT_RETENTION_DAYS_MAX = 36_500


class OrganizationCreateRequestSerializer(serializers.Serializer):
    """Schema-only — real validation in OrganizationValidationService."""

    name = serializers.CharField(max_length=255)
    audit_retention_days = serializers.IntegerField(
        min_value=0, max_value=AUDIT_RETENTION_DAYS_MAX, required=False, default=0
    )


class OrganizationRenameRequestSerializer(serializers.Serializer):
    """Schema-only — real validation in OrganizationValidationService.

    Both fields are optional, but at least one must be sent.
    """

    name = serializers.CharField(max_length=255, required=False)
    audit_retention_days = serializers.IntegerField(
        min_value=0, max_value=AUDIT_RETENTION_DAYS_MAX, required=False
    )


class OrganizationSettingsUpdateSerializer(serializers.Serializer):
    """Validate the org self-service settings PATCH body.

    This serializer is the only validation: OrganizationManagementService
    stores the value as given. 0 = unlimited (default).
    """

    audit_retention_days = serializers.IntegerField(min_value=0, max_value=AUDIT_RETENTION_DAYS_MAX)


class OrganizationConfigSerializer(serializers.ModelSerializer):
    """Nested under OrganizationResponseSerializer as `config` - same pattern
    as RealtimeAgentReadSerializer's openai_config/elevenlabs_config/
    gemini_config (each 1:1 sidecar config model gets its own dedicated
    ModelSerializer, nested by field name matching the relation's own
    related_name, rather than reaching across the relation with a dotted
    `source=` on the parent serializer).
    """

    class Meta:
        model = OrganizationConfig
        fields = ["audit_retention_days"]
        read_only_fields = fields


class OrganizationResponseSerializer(serializers.ModelSerializer):
    """Response shape for every Organization endpoint (list, create, rename,
    deactivate, reactivate, settings). `member_count` is supplied by the
    queryset annotation in OrganizationManagementService.
    """

    member_count = serializers.IntegerField(read_only=True)
    # Relies on the service layer's select_related("config").
    config = OrganizationConfigSerializer(read_only=True)

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "is_active",
            "member_count",
            "config",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class OrganizationAdminUserSerializer(serializers.ModelSerializer):
    """User shape embedded under `admins` in the organizations list response."""

    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "display_name", "avatar_url"]
        read_only_fields = fields

    def get_avatar_url(self, user) -> str | None:
        return build_avatar_url(user)


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
