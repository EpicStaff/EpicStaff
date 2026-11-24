from agents.models import Surface
from rest_framework import serializers

from tables.import_export.enums import EntityType
from tables.import_export.serializers.surface_knowledge import (
    SEARCH_CONFIG_RELATIONS,
    serialize_knowledge,
)
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin


class SurfaceImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Surface
        # group is an org-local label id: never exported, so an imported surface is
        # always ungrouped.
        exclude = ["org", "created_by", "owner_agent", "created_at", "updated_at", "group"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["tools"] = {
            EntityType.PYTHON_CODE_TOOL: list(
                instance.python_tools.values("python_tool_id", "mode")
            ),
            EntityType.MCP_TOOL: list(instance.mcp_tools.values("mcp_tool_id", "mode")),
        }
        ret["knowledge"] = serialize_knowledge(
            instance.knowledge.select_related("collection", *SEARCH_CONFIG_RELATIONS)
        )
        return ret
