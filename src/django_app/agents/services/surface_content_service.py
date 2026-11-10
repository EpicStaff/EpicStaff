from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from tables.models.base_models import copied_field_values

from agents.models.surface_models import (
    AgentInlineSurfaceGraphBasicSearchConfig,
    AgentInlineSurfaceGraphDriftSearchConfig,
    AgentInlineSurfaceGraphGlobalSearchConfig,
    AgentInlineSurfaceGraphLocalSearchConfig,
    AgentInlineSurfaceKnowledge,
    AgentInlineSurfaceMcpTool,
    AgentInlineSurfaceNaiveSearchConfig,
    AgentInlineSurfacePythonTool,
    AgentInlineSurfaceStorageItem,
    InlineSurfaceGraphBasicSearchConfig,
    InlineSurfaceGraphDriftSearchConfig,
    InlineSurfaceGraphGlobalSearchConfig,
    InlineSurfaceGraphLocalSearchConfig,
    InlineSurfaceKnowledge,
    InlineSurfaceMcpTool,
    InlineSurfaceNaiveSearchConfig,
    InlineSurfacePythonTool,
    InlineSurfaceStorageItem,
    StorageAccess,
    SurfaceGraphBasicSearchConfig,
    SurfaceGraphDriftSearchConfig,
    SurfaceGraphGlobalSearchConfig,
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
    graph_global_config: type[models.Model]
    graph_drift_config: type[models.Model]


CATALOG_SURFACE_CONTENT = SurfaceContentModels(
    parent_field="surface",
    python_tool=SurfacePythonTool,
    mcp_tool=SurfaceMcpTool,
    storage_item=SurfaceStorageItem,
    knowledge=SurfaceKnowledge,
    naive_config=SurfaceNaiveSearchConfig,
    graph_basic_config=SurfaceGraphBasicSearchConfig,
    graph_local_config=SurfaceGraphLocalSearchConfig,
    graph_global_config=SurfaceGraphGlobalSearchConfig,
    graph_drift_config=SurfaceGraphDriftSearchConfig,
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
    graph_global_config=InlineSurfaceGraphGlobalSearchConfig,
    graph_drift_config=InlineSurfaceGraphDriftSearchConfig,
)

AGENT_INLINE_SURFACE_CONTENT = SurfaceContentModels(
    parent_field="agent_inline_surface",
    python_tool=AgentInlineSurfacePythonTool,
    mcp_tool=AgentInlineSurfaceMcpTool,
    storage_item=AgentInlineSurfaceStorageItem,
    knowledge=AgentInlineSurfaceKnowledge,
    naive_config=AgentInlineSurfaceNaiveSearchConfig,
    graph_basic_config=AgentInlineSurfaceGraphBasicSearchConfig,
    graph_local_config=AgentInlineSurfaceGraphLocalSearchConfig,
    graph_global_config=AgentInlineSurfaceGraphGlobalSearchConfig,
    graph_drift_config=AgentInlineSurfaceGraphDriftSearchConfig,
)


# SurfaceKnowledge's optional one-to-one search configs use the same
# related_name on every surface family; `content_attr` picks the matching model
# class off the SurfaceContentModels bundle.
_SEARCH_CONFIG_RELATED_NAMES = (
    ("naive_search_config", "naive_config"),
    ("graph_basic_search_config", "graph_basic_config"),
    ("graph_local_search_config", "graph_local_config"),
    ("graph_global_search_config", "graph_global_config"),
    ("graph_drift_search_config", "graph_drift_config"),
)


class SurfaceContentService:
    """Replace or copy a surface's content rows (tools, storage items, knowledge).

    Parameterized by `SurfaceContentModels` so the same logic serves both the
    catalog `Surface` and the per-node `InlineSurface` families.
    """

    @staticmethod
    def copy_content(source_parent, new_parent, content: SurfaceContentModels, *, org_id) -> None:
        """Copy every live content row of `source_parent` onto `new_parent`.

        Tool and collection links are re-linked to the same rows, not cloned. Storage
        items pointing at a file outside `org_id` are skipped, so a copy never grants
        access to another organization's file.
        """
        source_owner = {content.parent_field: source_parent}
        new_owner = {content.parent_field: new_parent}

        # Re-linked rows are passed by id, so no row is fetched just to copy its key.
        for tool in content.python_tool.objects.filter(**source_owner):
            content.python_tool.objects.create(
                python_tool_id=tool.python_tool_id, mode=tool.mode, **new_owner
            )

        for tool in content.mcp_tool.objects.filter(**source_owner):
            content.mcp_tool.objects.create(
                mcp_tool_id=tool.mcp_tool_id, mode=tool.mode, **new_owner
            )

        for item in content.storage_item.objects.filter(
            **source_owner, storage_file__org_id=org_id
        ):
            content.storage_item.objects.create(
                storage_file_id=item.storage_file_id,
                can_list=item.can_list,
                can_view=item.can_view,
                can_edit=item.can_edit,
                can_delete=item.can_delete,
                **new_owner,
            )

        search_config_names = [related_name for related_name, _ in _SEARCH_CONFIG_RELATED_NAMES]
        for knowledge in content.knowledge.objects.filter(**source_owner).select_related(
            *search_config_names
        ):
            new_knowledge = content.knowledge.objects.create(
                collection_id=knowledge.collection_id, **new_owner
            )
            SurfaceContentService._copy_knowledge_search_configs(knowledge, new_knowledge, content)

    @staticmethod
    def _copy_knowledge_search_configs(
        source_knowledge, new_knowledge, content: SurfaceContentModels
    ) -> None:
        for related_name, content_attr in _SEARCH_CONFIG_RELATED_NAMES:
            try:
                config = getattr(source_knowledge, related_name)
            except ObjectDoesNotExist:
                continue

            config_model = getattr(content, content_attr)
            values = copied_field_values(config, exclude={"surface_knowledge"})
            config_model.objects.create(surface_knowledge=new_knowledge, **values)

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
            graph_global_data = item.get("graph_global_search_config")
            graph_drift_data = item.get("graph_drift_search_config")

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

            if graph_global_data is not None:
                content.graph_global_config.objects.create(
                    surface_knowledge=knowledge,
                    **graph_global_data,
                )

            if graph_drift_data is not None:
                content.graph_drift_config.objects.create(
                    surface_knowledge=knowledge,
                    **graph_drift_data,
                )
