from __future__ import annotations

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
        surface_dicts = [SurfaceReadSerializer(s).data for s in node.surface_list.all()]

        inline_surface = getattr(node, "inline_surface", None)
        if isinstance(inline_surface, AgentInlineSurface):
            surface_dicts.append(AgentInlineSurfaceReadSerializer(inline_surface).data)
        elif isinstance(inline_surface, InlineSurface):
            surface_dicts.append(InlineSurfaceReadSerializer(inline_surface).data)

        return SurfaceCombineService.combine(surface_dicts)
