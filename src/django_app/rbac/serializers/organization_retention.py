from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from src.shared.retention import DataType, allowed_org_values

from rbac.authorship.user_summary import UserSummarySerializer
from rbac.models import OrganizationConfig


class OrganizationRetentionUpdateRequestSerializer(serializers.Serializer):
    """Schema-only; real validation in OrganizationRetentionValidationService."""

    sessions_days = serializers.IntegerField(required=False, allow_null=True)
    conversations_days = serializers.IntegerField(required=False, allow_null=True)
    audit_days = serializers.IntegerField(required=False, allow_null=True)


class RetentionRuleSerializer(serializers.Serializer):
    default_days = serializers.IntegerField(read_only=True)
    max_days = serializers.IntegerField(read_only=True, allow_null=True)
    min_days = serializers.IntegerField(read_only=True, allow_null=True)
    allowed = serializers.ListField(child=serializers.IntegerField(), read_only=True)


class RetentionPolicySerializer(serializers.Serializer):
    sessions = RetentionRuleSerializer(read_only=True)
    conversations = RetentionRuleSerializer(read_only=True)
    audit = RetentionRuleSerializer(read_only=True)


class OrganizationRetentionResponseSerializer(serializers.Serializer):
    """An organization's retention: each type's chosen value (null = instance default),
    the days actually applied, and the instance policy that bounds the choices.

    Serializes an OrganizationConfig. `updated_at` and `updated_by` are null until the
    organization first changes its retention.
    """

    org_id = serializers.IntegerField(read_only=True)
    sessions_days = serializers.IntegerField(
        source="retention_sessions_days", read_only=True, allow_null=True
    )
    sessions_effective_days = serializers.SerializerMethodField()
    conversations_days = serializers.IntegerField(
        source="retention_conversations_days", read_only=True, allow_null=True
    )
    conversations_effective_days = serializers.SerializerMethodField()
    audit_days = serializers.IntegerField(
        source="retention_audit_days", read_only=True, allow_null=True
    )
    audit_effective_days = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(
        source="retention_updated_at", read_only=True, allow_null=True
    )
    updated_by = UserSummarySerializer(
        source="retention_updated_by", read_only=True, allow_null=True
    )
    retention_policy = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.INT)
    def get_sessions_effective_days(self, config: OrganizationConfig) -> int:
        return config.effective_retention_days(DataType.SESSIONS)

    @extend_schema_field(OpenApiTypes.INT)
    def get_conversations_effective_days(self, config: OrganizationConfig) -> int:
        return config.effective_retention_days(DataType.CONVERSATIONS)

    @extend_schema_field(OpenApiTypes.INT)
    def get_audit_effective_days(self, config: OrganizationConfig) -> int:
        return config.effective_retention_days(DataType.AUDIT)

    @extend_schema_field(RetentionPolicySerializer)
    def get_retention_policy(self, config: OrganizationConfig) -> dict:
        return {
            str(data_type): {
                "default_days": rule.default_days,
                "max_days": rule.max_days,
                "min_days": rule.min_days,
                "allowed": list(allowed_org_values(rule)),
            }
            for data_type, rule in settings.RETENTION_POLICY.rules.items()
        }
