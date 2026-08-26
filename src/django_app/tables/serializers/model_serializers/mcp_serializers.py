from django.db import transaction
from rest_framework import serializers

from tables.models.label_models import Label
from tables.models.mcp_models import McpTool
from tables.models.secret_models import Secret
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)
from tables.serializers.utils.org_scoped_labels import (
    org_scoped_label_ids,
    set_org_scoped_labels,
)


class McpToolSerializer(serializers.ModelSerializer):
    auth_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="auth_secret",
        required=False,
        allow_null=True,
    )
    is_favorite = serializers.BooleanField(read_only=True, default=False)

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
        exclude = ["auth_secret"]
        read_only_fields = ["org", "created_by"]

    def to_internal_value(self, data):
        if isinstance(data, dict) and data.get("labels") is None:
            data = {key: value for key, value in data.items() if key != "labels"}
        return super().to_internal_value(data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["labels"] = org_scoped_label_ids(
            instance, self.context.get("request")
        )
        return representation

    def create(self, validated_data):
        labels = validated_data.pop("labels", None) or []
        with transaction.atomic():
            instance = super().create(validated_data)
            set_org_scoped_labels(instance, labels, self.context.get("request"))
        return instance

    def update(self, instance, validated_data):
        labels = validated_data.pop("labels", None)
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            if labels is not None:
                set_org_scoped_labels(instance, labels, self.context.get("request"))
        return instance
