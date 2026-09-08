from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from agents.models.agent_models import (
    AgentDefaultSurface,
    AgentDefinition,
    SurfacePlace,
)
from agents.serializers.surface_serializers import SurfaceReadSerializer
from agents.services.surface_combine_service import SurfaceCombineService
from tables.models.graph_models import StorageFile
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.python_models import PythonCodeTool
from tables.services.rag_lookup_service import RagLookupService
from src.shared.models import (
    BaseToolData,
    GraphRagBasicSearchParams,
    GraphRagLocalSearchParams,
    GraphRagSearchConfig,
    NaiveRagSearchConfig,
    RagSearchConfig,
)

if TYPE_CHECKING:
    from tables.services.converter_service import ConverterService


@dataclass
class RealtimeAgentSurfaceResolution:
    tools: list[BaseToolData]
    knowledge_collection_id: int | None
    rag_type_id: str | None
    rag_search_config: RagSearchConfig | None
    rag_embedder_api_key_secret_id: int | None = None


class RealtimeSurfaceService:
    """Resolves an AgentDefinition's realtime tools + knowledge from its default surfaces."""

    def __init__(self, converter_service: ConverterService):
        self.converter_service = converter_service

    def resolve(
        self, agent_definition: AgentDefinition
    ) -> RealtimeAgentSurfaceResolution:
        combined_surface = self._build_combined_surface(agent_definition)

        storage_allowed_paths, storage_org_prefix = self._resolve_storage_grants(
            combined_surface["storage_items"]
        )
        tools = self._resolve_python_tools(
            combined_surface["python_tools"],
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            org_id=agent_definition.organization_id,
        )
        self._warn_on_mcp_tools(combined_surface["mcp_tools"])

        (
            knowledge_collection_id,
            rag_type_id,
            rag_search_config,
            rag_embedder_api_key_secret_id,
        ) = self._resolve_knowledge(combined_surface["knowledge"])

        return RealtimeAgentSurfaceResolution(
            tools=tools,
            knowledge_collection_id=knowledge_collection_id,
            rag_type_id=rag_type_id,
            rag_search_config=rag_search_config,
            rag_embedder_api_key_secret_id=rag_embedder_api_key_secret_id,
        )

    def _build_combined_surface(self, agent_definition: AgentDefinition) -> dict:
        all_default_surfaces = list(
            AgentDefaultSurface.objects.filter(
                agent_definition=agent_definition
            ).select_related("surface")
        )
        # Any explicit row for a surface — regardless of place — opts it out of
        # the implicit-ALL fallback below, even if that row scopes it to chat/flow.
        explicit_surface_ids = {row.surface_id for row in all_default_surfaces}

        surfaces = [
            row.surface
            for row in all_default_surfaces
            if row.place in (SurfacePlace.ALL, SurfacePlace.REALTIME)
        ]
        for surface in agent_definition.owned_surfaces.all():
            if surface.id not in explicit_surface_ids:
                surfaces.append(surface)

        surface_dicts = [SurfaceReadSerializer(surface).data for surface in surfaces]
        return SurfaceCombineService.combine(surface_dicts)

    def _resolve_python_tools(
        self,
        python_tool_entries: list[dict],
        storage_allowed_paths: list[str],
        storage_org_prefix: str | None,
        org_id: int | None,
    ) -> list[BaseToolData]:
        allowed_tool_ids = [
            entry["python_tool"]
            for entry in python_tool_entries
            if entry["mode"] == "allow"
        ]
        return [
            self.converter_service.convert_tool_to_base_tool_pydantic(
                python_tool,
                storage_allowed_paths_override=storage_allowed_paths,
                storage_org_prefix_override=storage_org_prefix,
                org_id_override=org_id,
            )
            for python_tool in PythonCodeTool.objects.filter(pk__in=allowed_tool_ids)
        ]

    def _resolve_storage_grants(
        self, storage_item_entries: list[dict]
    ) -> tuple[list[str], str | None]:
        """Resolve allowed storage paths + org prefix from the agent-definition's
        own surface, mirroring the inclusion rule in
        `base_node_payload_service.BaseNodePayloadService._build_s3_pool`: a
        `StorageFile` qualifies if it has any ALLOW flag among
        can_list/can_view/can_edit/can_delete.
        """
        allowed_file_ids = [
            entry["storage_file"]
            for entry in storage_item_entries
            if "allow"
            in (
                entry.get("can_list", "unset"),
                entry.get("can_view", "unset"),
                entry.get("can_edit", "unset"),
                entry.get("can_delete", "unset"),
            )
        ]
        if not allowed_file_ids:
            return [], None

        storage_files = list(StorageFile.objects.filter(pk__in=allowed_file_ids))
        if not storage_files:
            return [], None

        allowed_paths = [storage_file.path for storage_file in storage_files]
        org_id = storage_files[0].org_id
        storage_org_prefix = f"org_{org_id}" if org_id is not None else None
        return allowed_paths, storage_org_prefix

    def _warn_on_mcp_tools(self, mcp_tool_entries: list[dict]) -> None:
        for entry in mcp_tool_entries:
            if entry["mode"] != "allow":
                continue

            logger.warning(
                "MCP tool {} skipped for realtime agent — realtime service has no MCP executor.",
                entry["mcp_tool"],
            )

    def _resolve_knowledge(
        self, knowledge_entries: list[dict]
    ) -> tuple[int | None, str | None, RagSearchConfig | None, int | None]:
        if not knowledge_entries:
            return None, None, None, None

        if len(knowledge_entries) > 1:
            logger.warning(
                "Realtime agent combined surface has {} knowledge collections, only the first is used.",
                len(knowledge_entries),
            )

        knowledge = knowledge_entries[0]
        collection_id = knowledge["collection"]

        if knowledge.get("naive_search_config") is not None:
            return self._resolve_naive_rag(
                collection_id, knowledge["naive_search_config"]
            )

        if (
            knowledge.get("graph_basic_search_config") is not None
            or knowledge.get("graph_local_search_config") is not None
        ):
            return self._resolve_graph_rag(collection_id, knowledge)

        logger.warning(
            "Collection {} has no usable RAG search config, skipping.", collection_id
        )
        return None, None, None, None

    def _resolve_naive_rag(
        self, collection_id: int, naive_config: dict
    ) -> tuple[int | None, str | None, RagSearchConfig | None, int | None]:
        naive_rag = RagLookupService.latest_rag(
            NaiveRag, collection_id, pk_field="naive_rag_id"
        )
        if (
            naive_rag is None
            or naive_rag.rag_status != NaiveRag.NaiveRagStatus.COMPLETED
        ):
            logger.warning(
                "No completed NaiveRag for collection {}, skipping.", collection_id
            )
            return None, None, None, None

        rag_type_id = f"naive:{naive_rag.naive_rag_id}"
        rag_search_config = NaiveRagSearchConfig(
            search_limit=naive_config["search_limit"],
            similarity_threshold=float(naive_config["similarity_threshold"]),
        )
        embedder_secret_id = (
            naive_rag.embedder.api_key_secret_id if naive_rag.embedder else None
        )
        return collection_id, rag_type_id, rag_search_config, embedder_secret_id

    def _resolve_graph_rag(
        self, collection_id: int, knowledge: dict
    ) -> tuple[int | None, str | None, RagSearchConfig | None, int | None]:
        graph_rag = RagLookupService.latest_rag(
            GraphRag, collection_id, pk_field="graph_rag_id"
        )
        if (
            graph_rag is None
            or graph_rag.rag_status != GraphRag.GraphRagStatus.COMPLETED
        ):
            logger.warning(
                "No completed GraphRag for collection {}, skipping.", collection_id
            )
            return None, None, None, None

        rag_type_id = f"graph:{graph_rag.graph_rag_id}"

        basic_config = knowledge.get("graph_basic_search_config")
        if basic_config is not None:
            search_params = GraphRagBasicSearchParams(**basic_config)
        else:
            search_params = GraphRagLocalSearchParams(
                **knowledge["graph_local_search_config"]
            )

        rag_search_config = GraphRagSearchConfig(search_params=search_params)
        embedder_secret_id = (
            graph_rag.embedder.api_key_secret_id if graph_rag.embedder else None
        )
        return collection_id, rag_type_id, rag_search_config, embedder_secret_id
