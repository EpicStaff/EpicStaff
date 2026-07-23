from tables.serializers.utils.secret_fields import SecretCharField
from rest_framework import serializers

from tables.models.label_models import Label
from tables.models.mcp_models import McpTool
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)


class McpToolSerializer(serializers.ModelSerializer):
    auth = SecretCharField()
    # Per-org unique name → clean 400 instead of a DB IntegrityError (500).
    name = serializers.CharField(
        validators=[
            OrgScopedUniqueValidator(
                queryset=McpTool.objects.all(),
                message="An MCP tool with this name already exists.",
            )
        ]
    )
    labels = OrgScopedPrimaryKeyRelatedField(
        many=True,
        required=False,
        queryset=Label.objects.filter(scope=Label.Scope.TOOL),
    )

    class Meta:
        model = McpTool
        fields = "__all__"
        read_only_fields = ["org", "created_by"]

    def to_internal_value(self, data):
        # McpToolViewSet.update() back-fills every concrete field missing from
        # the request body (including this M2M) with its model default before
        # validating, which for `labels` is an explicit `None` — DRF's
        # ManyRelatedField doesn't support `allow_null`, so treat that specific
        # None the same as the field being entirely absent ("leave as is" in
        # update(), below). An explicit `[]` still clears the assignment.
        if isinstance(data, dict) and data.get("labels") is None:
            data = {key: value for key, value in data.items() if key != "labels"}
        return super().to_internal_value(data)

    def create(self, validated_data):
        labels = validated_data.pop("labels", None) or []
        instance = super().create(validated_data)
        instance.labels.set(labels)
        return instance

    def update(self, instance, validated_data):
        labels = validated_data.pop("labels", None)
        instance = super().update(instance, validated_data)
        if labels is not None:
            instance.labels.set(labels)
        return instance
