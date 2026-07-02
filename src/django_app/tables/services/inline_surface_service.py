from __future__ import annotations

from django.db import transaction

from tables.models.agent_models.surface_models import InlineSurface
from tables.services.surface_content_service import (
    INLINE_SURFACE_CONTENT,
    SurfaceContentService,
)


class InlineSurfaceService:
    """Owns create / full-replace / delete of a TaskNode's InlineSurface.

    `data=None` deletes the inline surface (and its content, via CASCADE).
    A dict upserts the scalar fields and fully replaces every content list.
    """

    @staticmethod
    @transaction.atomic
    def apply(*, task_node, data):
        if data is None:
            InlineSurface.objects.filter(task_node=task_node).delete()
            return None

        inline, _ = InlineSurface.objects.update_or_create(
            task_node=task_node,
            defaults={
                "instructions": data.get("instructions", ""),
                "allow_creation": data.get("allow_creation", False),
            },
        )

        SurfaceContentService.replace_python_tools(
            inline, data.get("python_tools", []), INLINE_SURFACE_CONTENT
        )
        SurfaceContentService.replace_mcp_tools(
            inline, data.get("mcp_tools", []), INLINE_SURFACE_CONTENT
        )
        SurfaceContentService.replace_storage_items(
            inline, data.get("storage_items", []), INLINE_SURFACE_CONTENT
        )
        SurfaceContentService.replace_knowledge(
            inline, data.get("knowledge", []), INLINE_SURFACE_CONTENT
        )

        return inline
