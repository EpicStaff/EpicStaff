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
        # Flow labels and Tool labels are independent trees (Label.scope) —
        # both the parent-tree check below and the name-uniqueness check
        # further down must stay within the tree the owning viewset serves.
        # `label_scope` is a fixed attribute on both LabelViewSet and
        # ToolLabelViewSet; fall back to the instance's own scope on update if
        # the serializer is ever used outside a view with that attribute.
        view = self.context.get("view")
        scope = getattr(view, "label_scope", None)
        if scope is None and self.instance is not None:
            scope = self.instance.scope

        # A label may only be parented under a label of its own scope —
        # otherwise a Flow label could be parented under a Tool label (or vice
        # versa), silently merging the two independent trees (full_path would
        # then walk across scopes, and no DB constraint catches it).
        if "parent" in attrs:
            parent = attrs["parent"]
            if parent is not None and parent.scope != scope:
                raise serializers.ValidationError(
                    {"parent": "Parent label must belong to the same label tree (scope)."}
                )

        name = attrs.get("name")
        if name is None:  # partial update not touching the name
            return attrs
        parent = attrs.get("parent")

        org_id = resolve_active_org_id(self.context["request"])
        qs = Label.objects.filter(org_id=org_id, name=name, scope=scope)
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
