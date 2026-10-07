from rbac.scoping.fields import OrgScopedUniqueValidator
from rest_framework import serializers
from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.validators.audit_filter_body_validator import validate_filter_body_shape


class AuditFilterPresetSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=150,
        validators=[
            OrgScopedUniqueValidator(
                queryset=AuditFilterPreset.objects.all(),
                message="A preset with this name already exists in this organization.",
            )
        ],
    )
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = AuditFilterPreset
        fields = ["id", "name", "filter_body", "is_owner", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_is_owner(self, preset: AuditFilterPreset) -> bool:
        return preset.created_by_id == self.context["request"].user.id

    def validate_filter_body(self, value):
        return validate_filter_body_shape(value)


class AuditFilterPresetCopySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False, allow_blank=False)


class AuditFilterPresetImportFileSerializer(serializers.Serializer):
    """The actual upload - a `.json` file, exactly what `export`/`bulk_export`
    produce, attached as multipart/form-data (matches the Agent/Crew/Graph
    import convention - see ImportRequestSerializer) rather than pasted as
    a raw JSON request body. Each preset in it is then validated by
    AuditFilterPresetEntitySerializer inside AuditFilterPresetStrategy."""

    file = serializers.FileField()
