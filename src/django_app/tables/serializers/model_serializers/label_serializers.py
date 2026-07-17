from rest_framework import serializers

from tables.models.label_models import Label
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    resolve_active_org_id,
)


class LabelSerializer(serializers.ModelSerializer):
    full_path = serializers.CharField(read_only=True)
    # A label may only be parented under another label in the active org.
    parent = OrgScopedPrimaryKeyRelatedField(
        queryset=Label.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Label
        fields = ["id", "name", "parent", "created_at", "metadata", "full_path"]
        read_only_fields = ["id", "created_at", "full_path"]
        extra_kwargs = {
            "name": {"validators": []},
        }

    def validate(self, attrs):
        name = attrs.get("name")
        if name is None:  # partial update not touching the name
            return attrs
        parent = attrs.get("parent")

        org_id = resolve_active_org_id(self.context["request"])
        qs = Label.objects.filter(org_id=org_id, name=name)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)

        if parent is None:
            if qs.filter(parent__isnull=True).exists():
                raise serializers.ValidationError(
                    {"name": "Top-level label with this name already exists."}
                )
        else:
            if qs.filter(parent=parent).exists():
                raise serializers.ValidationError(
                    {"name": "Label with this name already exists under this parent."}
                )

        return attrs
