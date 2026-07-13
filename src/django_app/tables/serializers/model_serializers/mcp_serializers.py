from tables.serializers.utils.secret_fields import SecretCharField
from rest_framework import serializers

from tables.models.mcp_models import McpTool


class McpToolSerializer(serializers.ModelSerializer):
    auth = SecretCharField()

    class Meta:
        model = McpTool
        fields = "__all__"
