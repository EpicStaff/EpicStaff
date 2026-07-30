from rest_framework import serializers

from tables.models.label_models import Label
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    resolve_active_org_id,
)


class LabelSerializer(serializers.ModelSerializer):
    full_path = serializers.SerializerMethodField()
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

    def get_full_path(self, obj):
        full_paths = self.context.get("full_paths")
        if full_paths is not None and obj.id in full_paths:
            return full_paths[obj.id]
        return obj.full_path

    def _validate_no_parent_cycle(self, parent):
        """Reject a `parent` that is self, or a descendant of self — either
        would create a cycle that `Label.full_path` (and any other
        parent-chain walk) could loop or recurse on forever.

        Walks up from `parent` via `.parent_id`, using a `visited` set so a
        chain already corrupted in stored data (e.g. rows written before this
        validation existed) can't hang this walk either.
        """
        self_pk = self.instance.pk
        if parent.pk == self_pk:
            raise serializers.ValidationError(
                {"parent": "A label cannot be its own parent."}
            )

        visited = set()
        current_id = parent.parent_id
        while current_id is not None:
            if current_id == self_pk:
                raise serializers.ValidationError(
                    {
                        "parent": "This parent is a descendant of the label being "
                        "updated — assigning it would create a parent loop."
                    }
                )
            if current_id in visited:
                # Pre-existing corrupt cycle in stored data unrelated to self —
                # stop walking rather than loop forever.
                break
            visited.add(current_id)
            row = Label.objects.filter(pk=current_id).values_list(
                "parent_id", flat=True
            ).first()
            current_id = row

    def validate(self, attrs):
        view = self.context.get("view")
        scope = getattr(view, "label_scope", None)
        if scope is None and self.instance is not None:
            scope = self.instance.scope

        if "parent" in attrs:
            parent = attrs["parent"]
            if parent is not None and parent.scope != scope:
                raise serializers.ValidationError(
                    {
                        "parent": "Parent label must belong to the same label tree (scope)."
                    }
                )
            if parent is not None and self.instance is not None:
                self._validate_no_parent_cycle(parent)

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
