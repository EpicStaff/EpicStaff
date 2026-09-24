from rest_framework import serializers

from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.serializers.org_scoped_fields import resolve_active_org_id
from tables.validators.audit_filter_body_validator import validate_filter_body_shape


class AuditFilterPresetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditFilterPreset
        fields = ["id", "name", "filter_body", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_filter_body(self, value):
        return validate_filter_body_shape(value)

    def validate(self, attrs):
        name = attrs.get("name")
        if name is None:  # partial update not touching the name
            return attrs

        request = self.context["request"]
        org_id = resolve_active_org_id(request)
        qs = AuditFilterPreset.objects.filter(
            org_id=org_id, created_by=request.user, name=name
        )
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {"name": "You already have a preset with this name."}
            )
        return attrs


class AuditFilterPresetCopySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False, allow_blank=False)


class AuditFilterPresetImportFileSerializer(serializers.Serializer):
    """The actual upload - a `.json` file, exactly what `export`/`bulk_export`
    produce, attached as multipart/form-data (matches the Agent/Crew/Graph
    import convention - see ImportRequestSerializer) rather than pasted as
    a raw JSON request body. Each preset in it is then validated by
    AuditFilterPresetEntitySerializer inside AuditFilterPresetStrategy."""

    file = serializers.FileField()
