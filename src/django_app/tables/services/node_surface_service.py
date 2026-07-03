from __future__ import annotations

from tables.serializers.model_serializers.inline_surface_serializers import (
    InlineSurfaceReadSerializer,
)
from tables.serializers.model_serializers.surface_serializers import (
    SurfaceReadSerializer,
)
from tables.services.surface_combine_service import SurfaceCombineService


class NodeSurfaceService:
    @staticmethod
    def build_combined_surface(node) -> dict:
        surface_dicts = [SurfaceReadSerializer(s).data for s in node.surface_list.all()]

        inline_surface = getattr(node, "inline_surface", None)
        if inline_surface is not None:
            surface_dicts.append(InlineSurfaceReadSerializer(inline_surface).data)

        return SurfaceCombineService.combine(surface_dicts)
