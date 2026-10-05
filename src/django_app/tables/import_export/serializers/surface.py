from agents.models import Surface
from rest_framework import serializers

from tables.import_export.enums import EntityType
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin


class SurfaceImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
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
