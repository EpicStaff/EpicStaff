from rest_framework import serializers

from tables.models.audit_filter_preset_models import AuditFilterPreset, AuditPresetDomain
from tables.validators.audit_filter_body_validator import validate_filter_body_shape


class AuditFilterPresetEntitySerializer(serializers.ModelSerializer):
    """A preset in an export file. A file from before presets had a domain carries none:
    it holds session-audit presets."""

    class Meta:
        model = AuditFilterPreset
        fields = ["id", "name", "filter_body", "domain"]

    def validate(self, attrs):
        validate_filter_body_shape(
            attrs.get("filter_body", {}), attrs.get("domain", AuditPresetDomain.SESSIONS)
        )
        return attrs
