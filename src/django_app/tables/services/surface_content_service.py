from __future__ import annotations

from dataclasses import dataclass

from django.db import models

from tables.models.agent_models.surface_models import (
    InlineSurfaceGraphBasicSearchConfig,
    InlineSurfaceGraphLocalSearchConfig,
    InlineSurfaceKnowledge,
    InlineSurfaceMcpTool,
    InlineSurfaceNaiveSearchConfig,
    InlineSurfacePythonTool,
    InlineSurfaceStorageItem,
    StorageAccess,
    SurfaceGraphBasicSearchConfig,
    SurfaceGraphLocalSearchConfig,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfaceNaiveSearchConfig,
    SurfacePythonTool,
    SurfaceStorageItem,
)


@dataclass(frozen=True)
class SurfaceContentModels:
    """Bundles the content model set for one surface family (catalog or inline).

    `parent_field` is the FK/O2O name each content model uses to point back at
    its owning surface (e.g. "surface" or "inline_surface").
    """

    parent_field: str
    python_tool: type[models.Model]
    mcp_tool: type[models.Model]
    storage_item: type[models.Model]
    knowledge: type[models.Model]
    naive_config: type[models.Model]
    graph_basic_config: type[models.Model]
    graph_local_config: type[models.Model]


CATALOG_SURFACE_CONTENT = SurfaceContentModels(
    parent_field="surface",
    python_tool=SurfacePythonTool,
    mcp_tool=SurfaceMcpTool,
    storage_item=SurfaceStorageItem,
    knowledge=SurfaceKnowledge,
    naive_config=SurfaceNaiveSearchConfig,
    graph_basic_config=SurfaceGraphBasicSearchConfig,
    graph_local_config=SurfaceGraphLocalSearchConfig,
)

INLINE_SURFACE_CONTENT = SurfaceContentModels(
    parent_field="inline_surface",
    python_tool=InlineSurfacePythonTool,
    mcp_tool=InlineSurfaceMcpTool,
    storage_item=InlineSurfaceStorageItem,
    knowledge=InlineSurfaceKnowledge,
    naive_config=InlineSurfaceNaiveSearchConfig,
    graph_basic_config=InlineSurfaceGraphBasicSearchConfig,
    graph_local_config=InlineSurfaceGraphLocalSearchConfig,
)


class SurfaceContentService:
    """Delete-all + bulk-create replacement of a surface's content rows.

    Parameterized by `SurfaceContentModels` so the same logic serves both the
    catalog `Surface` and the per-node `InlineSurface` families.
    """

    @staticmethod
    def replace_python_tools(parent, items, content: SurfaceContentModels):
        filter_kwargs = {content.parent_field: parent}
        content.python_tool.objects.filter(**filter_kwargs).delete()

        content.python_tool.objects.bulk_create(
            [
                content.python_tool(
                    python_tool=item["python_tool"],
                    mode=item["mode"],
                    **filter_kwargs,
                )
                for item in items
            ]
        )

    @staticmethod
    def replace_mcp_tools(parent, items, content: SurfaceContentModels):
        filter_kwargs = {content.parent_field: parent}
        content.mcp_tool.objects.filter(**filter_kwargs).delete()

        content.mcp_tool.objects.bulk_create(
            [
                content.mcp_tool(
                    mcp_tool=item["mcp_tool"],
                    mode=item["mode"],
                    **filter_kwargs,
                )
                for item in items
            ]
        )

    @staticmethod
    def replace_storage_items(parent, items, content: SurfaceContentModels):
        filter_kwargs = {content.parent_field: parent}
        content.storage_item.objects.filter(**filter_kwargs).delete()

        content.storage_item.objects.bulk_create(
            [
                content.storage_item(
                    storage_file=item["storage_file"],
                    can_list=item.get("can_list", StorageAccess.UNSET),
                    can_view=item.get("can_view", StorageAccess.UNSET),
                    can_edit=item.get("can_edit", StorageAccess.UNSET),
                    can_delete=item.get("can_delete", StorageAccess.UNSET),
                    **filter_kwargs,
                )
                for item in items
            ]
        )

    @staticmethod
    def replace_knowledge(parent, items, content: SurfaceContentModels):
        filter_kwargs = {content.parent_field: parent}
        content.knowledge.objects.filter(**filter_kwargs).delete()

        for item in items:
            knowledge = content.knowledge.objects.create(
                collection=item["collection"],
                **filter_kwargs,
            )

            naive_config_data = item.get("naive_search_config")
            graph_basic_data = item.get("graph_basic_search_config")
            graph_local_data = item.get("graph_local_search_config")

            if naive_config_data is not None:
                content.naive_config.objects.create(
                    surface_knowledge=knowledge,
                    **naive_config_data,
                )

            if graph_basic_data is not None:
                content.graph_basic_config.objects.create(
                    surface_knowledge=knowledge,
                    **graph_basic_data,
                )

            if graph_local_data is not None:
                content.graph_local_config.objects.create(
                    surface_knowledge=knowledge,
                    **graph_local_data,
                )
