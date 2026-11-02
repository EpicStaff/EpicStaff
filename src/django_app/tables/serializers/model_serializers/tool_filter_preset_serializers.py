from rbac.scoping.fields import resolve_active_org_id
from rest_framework import serializers
from tables.models.tool_filter_preset_models import ToolFilterPreset
from tables.validators.tool_filter_body_validator import validate_tool_filter_body_shape


class ToolFilterPresetSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=150)

    class Meta:
        model = ToolFilterPreset
        fields = [
            "id",
            "name",
            "filter_body",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_filter_body(self, value):
        return validate_tool_filter_body_shape(value)

    def validate(self, attrs):
        name = attrs.get("name")
        if name is None:  # partial update not touching the name
            return attrs

        request = self.context["request"]
        org_id = resolve_active_org_id(request)
        qs = ToolFilterPreset.objects.filter(org_id=org_id, created_by=request.user, name=name)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({"name": "You already have a preset with this name."})
        return attrs
