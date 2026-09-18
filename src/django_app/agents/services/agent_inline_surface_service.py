from __future__ import annotations

from django.db import transaction

from agents.models.surface_models import AgentInlineSurface
from agents.services.surface_content_service import (
    AGENT_INLINE_SURFACE_CONTENT,
    SurfaceContentService,
)


class AgentInlineSurfaceService:
    """Owns create / full-replace / delete of an AgentNode's AgentInlineSurface.

    `data=None` deletes the inline surface (and its content, via CASCADE).
    A dict upserts the scalar fields and fully replaces every content list.
    """

    @staticmethod
    @transaction.atomic
    def apply(*, agent_node, data):
        if data is None:
            AgentInlineSurface.objects.filter(agent_node=agent_node).delete()
            return None

        inline, _ = AgentInlineSurface.objects.update_or_create(
            agent_node=agent_node,
            defaults={
                "instructions": data.get("instructions", ""),
            },
        )

        SurfaceContentService.replace_python_tools(
            inline, data.get("python_tools", []), AGENT_INLINE_SURFACE_CONTENT
        )
        SurfaceContentService.replace_mcp_tools(
            inline, data.get("mcp_tools", []), AGENT_INLINE_SURFACE_CONTENT
        )
        SurfaceContentService.replace_storage_items(
            inline, data.get("storage_items", []), AGENT_INLINE_SURFACE_CONTENT
        )
        SurfaceContentService.replace_knowledge(
            inline, data.get("knowledge", []), AGENT_INLINE_SURFACE_CONTENT
        )

        return inline
