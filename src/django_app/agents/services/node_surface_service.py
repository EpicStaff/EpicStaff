from __future__ import annotations

from django.db.models import prefetch_related_objects

from agents.models.surface_models import AgentInlineSurface, InlineSurface
from agents.serializers.inline_surface_serializers import (
    AgentInlineSurfaceReadSerializer,
    InlineSurfaceReadSerializer,
)
from agents.serializers.surface_serializers import (
    SurfaceReadSerializer,
)
from agents.services.surface_combine_service import SurfaceCombineService


class NodeSurfaceService:
    @staticmethod
    def build_combined_surface(node) -> dict:
        surfaces = list(node.surface_list.all())
        prefetch_related_objects(surfaces, "last_edits")
        surface_dicts = [SurfaceReadSerializer(surface).data for surface in surfaces]

        inline_surface = getattr(node, "inline_surface", None)
        if isinstance(inline_surface, AgentInlineSurface):
            surface_dicts.append(AgentInlineSurfaceReadSerializer(inline_surface).data)
        elif isinstance(inline_surface, InlineSurface):
            surface_dicts.append(InlineSurfaceReadSerializer(inline_surface).data)

        return SurfaceCombineService.combine(surface_dicts)
