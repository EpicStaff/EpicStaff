from rest_framework import serializers

from tables.models.mcp_models import McpTool
from tables.serializers.org_scoped_fields import OrgScopedUniqueValidator


class McpToolSerializer(serializers.ModelSerializer):
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
        fields = "__all__"
        read_only_fields = ["org", "created_by"]
