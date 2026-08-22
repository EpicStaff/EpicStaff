from rest_framework import serializers

from tables.models.mcp_models import McpTool
from tables.models.secret_models import Secret
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)


class McpToolSerializer(serializers.ModelSerializer):
    auth_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="auth_secret",
        required=False,
        allow_null=True,
    )
    # Per-org unique name → clean 400 instead of a DB IntegrityError (500).
    name = serializers.CharField(
        validators=[
            OrgScopedUniqueValidator(
                queryset=McpTool.objects.all(),
                message="An MCP tool with this name already exists.",
            )
        ]
    )

    class Meta:
        model = McpTool
        exclude = ["auth_secret"]
        read_only_fields = ["org", "created_by"]
