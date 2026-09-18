from rest_framework import serializers

from tables.models.audit_filter_preset_models import AuditFilterPreset


class AuditFilterPresetEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditFilterPreset
        fields = ["id", "name", "filter_body"]
