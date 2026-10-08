from rest_framework import serializers

from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.validators.audit_filter_body_validator import validate_filter_body_shape


class AuditFilterPresetEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditFilterPreset
        fields = ["id", "name", "filter_body"]

    def validate_filter_body(self, value):
        return validate_filter_body_shape(value)
