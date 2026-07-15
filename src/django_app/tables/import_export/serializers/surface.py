from rest_framework import serializers

from tables.models import Surface
from tables.import_export.enums import EntityType


class SurfaceImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Surface
        exclude = ["organization", "owner_agent"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["tools"] = {
            EntityType.PYTHON_CODE_TOOL: list(
                instance.python_tools.values("python_tool_id", "mode")
            ),
            EntityType.MCP_TOOL: list(instance.mcp_tools.values("mcp_tool_id", "mode")),
        }
        return ret
