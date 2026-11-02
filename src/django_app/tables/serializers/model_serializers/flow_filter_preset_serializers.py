from rbac.scoping.fields import resolve_active_org_id
from rest_framework import serializers
from tables.models.flow_filter_preset_models import FlowFilterPreset
from tables.validators.flow_filter_body_validator import validate_flow_filter_body_shape


class FlowFilterPresetSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=150)

    class Meta:
        model = FlowFilterPreset
        fields = [
            "id",
            "name",
            "filter_body",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_filter_body(self, value):
        return validate_flow_filter_body_shape(value)

    def validate(self, attrs):
        name = attrs.get("name")
        if name is None:  # partial update not touching the name
            return attrs

        request = self.context["request"]
        org_id = resolve_active_org_id(request)
        qs = FlowFilterPreset.objects.filter(org_id=org_id, created_by=request.user, name=name)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({"name": "You already have a preset with this name."})
        return attrs
