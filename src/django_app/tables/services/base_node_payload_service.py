from __future__ import annotations

from loguru import logger

from agents.models import AgentDefinition
from tables.models.graph_models import GraphStorageFile, StorageFile
from tables.models.knowledge_models.collection_models import SourceCollection
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeTool
from tables.services.converter_service import ConverterService
from tables.services.rag_lookup_service import RagLookupService
from src.shared.models import (
    AgentDefinitionData,
    BaseToolData,
    CollectionSpec,
    CombinedSurfaceData,
    CombinedSurfaceKnowledgeData,
    GraphRagBasicSearchParams,
    GraphRagDriftSearchParams,
    GraphRagGlobalSearchParams,
    GraphRagLocalSearchParams,
    GraphRagSearchConfig,
    NaiveRagSearchConfig,
    S3FileSpec,
    SearchConfigEntry,
)


class BaseNodePayloadService:
    """Shared helpers for building node payloads consumed by the agent service.

    Owns agent-definition hydration and the tool/collection/s3 resource-pool
    derivation from a node's combined surface. Node-type-specific payload
    services subclass this and add only their own assembly logic.
    """

    def __init__(self, converter_service: ConverterService):
        self.converter_service = converter_service

    def _build_agent_definition_data(
        self, agent_definition: AgentDefinition | None
    ) -> AgentDefinitionData | None:
        if agent_definition is None:
            return None

        agent_definition.fill_with_defaults()

        return AgentDefinitionData(
            id=agent_definition.id,
            name=agent_definition.name,
            description=agent_definition.description,
            instructions=agent_definition.instructions,
            llm_config_id=agent_definition.llm_config_id,
            fcm_llm_config_id=agent_definition.fcm_llm_config_id,
            max_iter=agent_definition.max_iter,
            max_rpm=agent_definition.max_rpm,
            max_execution_time=agent_definition.max_execution_time,
            cache=agent_definition.cache,
            max_retry_limit=agent_definition.max_retry_limit,
            default_temperature=agent_definition.default_temperature,
            max_tool_calls=agent_definition.max_tool_calls,
            tool_timeout=agent_definition.tool_timeout,
            max_consecutive_failures=agent_definition.max_consecutive_failures,
            schema_max_retries=agent_definition.schema_max_retries,
            llm=self.converter_service.convert_llm_config_to_pydantic(
                agent_definition.llm_config
            ),
            fcm_llm=self.converter_service.convert_llm_config_to_pydantic(
                agent_definition.fcm_llm_config
            ),
        )

    def _build_tool_pool(
        self,
        combined_surface: CombinedSurfaceData,
        graph_id: int | None,
        session_id: int | None,
        s3_files: list[S3FileSpec],
    ) -> list[BaseToolData]:
        allowed_python_tool_ids = [
            entry.python_tool
            for entry in combined_surface.python_tools
            if entry.mode == "allow"
        ]
        allowed_mcp_tool_ids = [
            entry.mcp_tool
            for entry in combined_surface.mcp_tools
            if entry.mode == "allow"
        ]
        surface_storage_paths = [spec.path for spec in s3_files]

        tools: list[BaseToolData] = []

        for python_tool in PythonCodeTool.objects.filter(
            pk__in=allowed_python_tool_ids
        ):
            tools.append(
                self.converter_service.convert_tool_to_base_tool_pydantic(
                    python_tool,
                    graph_id=graph_id,
                    session_id=session_id,
                    storage_allowed_paths_override=surface_storage_paths,
                )
            )

        for mcp_tool in McpTool.objects.filter(pk__in=allowed_mcp_tool_ids):
            tools.append(
                self.converter_service.convert_tool_to_base_tool_pydantic(mcp_tool)
            )

        return tools

    def _build_s3_pool(
        self, combined_surface: CombinedSurfaceData, graph_id: int | None
    ) -> list[S3FileSpec]:
        """Resolve the node's s3 file pool from its surface, capped by the flow.

        The surface grants determine which files a node MAY access; the flow's
        attached files/folders (GraphStorageFile) determine which paths EXIST
        for this run. Effective pool = surface grants ∩ flow-attached paths,
        where a surface-granted path passes the ceiling if it exactly matches
        a flow-attached path or sits inside a flow-attached folder. A surface
        grant broader than the flow attachment (e.g. surface grants a folder,
        flow only attached one file in it) does not pass — the flow attachment
        is a ceiling, never narrowed back out for the user. When `graph_id` is
        None (standalone / non-flow runs), the flow ceiling does not apply and
        the surface stays authoritative.
        """
        access_flags_by_file_id = {
            entry.storage_file: entry for entry in combined_surface.storage_items
        }
        allowed_file_ids = [
            file_id
            for file_id, entry in access_flags_by_file_id.items()
            if "allow"
            in (entry.can_list, entry.can_view, entry.can_edit, entry.can_delete)
        ]

        storage_files = list(StorageFile.objects.filter(pk__in=allowed_file_ids))
        if graph_id is not None:
            storage_files = self._filter_within_flow_ceiling(storage_files, graph_id)

        s3_files: list[S3FileSpec] = []
        for storage_file in storage_files:
            entry = access_flags_by_file_id[storage_file.pk]
            s3_files.append(
                S3FileSpec(
                    id=storage_file.pk,
                    path=storage_file.path,
                    metadata={
                        "name": storage_file.name,
                        "item_type": storage_file.item_type,
                        "size": storage_file.size,
                        "flags": {
                            "can_list": entry.can_list,
                            "can_view": entry.can_view,
                            "can_edit": entry.can_edit,
                            "can_delete": entry.can_delete,
                        },
                    },
                )
            )

        return s3_files

    def _filter_within_flow_ceiling(
        self, storage_files: list[StorageFile], graph_id: int
    ) -> list[StorageFile]:
        """Keep only `storage_files` whose path is covered by a path the flow
        attached: an exact match, or nested inside an attached folder (whose
        path always ends with '/'). Drops and logs anything a surface grants
        that the flow never attached — a narrower grant than the flow
        attachment still passes (e.g. flow attaches a folder, surface grants
        one file in it); a broader one does not (surface grants a folder, flow
        only attached one file in it)."""
        attached_paths = set(
            GraphStorageFile.objects.filter(graph_id=graph_id).values_list(
                "storage_file__path", flat=True
            )
        )
        attached_folder_paths = [path for path in attached_paths if path.endswith("/")]

        kept: list[StorageFile] = []
        for storage_file in storage_files:
            if self._path_within_flow_ceiling(
                storage_file.path, attached_paths, attached_folder_paths
            ):
                kept.append(storage_file)
                continue

            logger.warning(
                "StorageFile {} (path={}) is granted by the surface but not "
                "attached to graph {}; dropping it from the s3 pool.",
                storage_file.pk,
                storage_file.path,
                graph_id,
            )

        return kept

    @staticmethod
    def _path_within_flow_ceiling(
        path: str, attached_paths: set[str], attached_folder_paths: list[str]
    ) -> bool:
        if path in attached_paths:
            return True

        return any(
            path.startswith(folder_path) for folder_path in attached_folder_paths
        )

    def _build_collection_pool(
        self, combined_surface: CombinedSurfaceData
    ) -> list[CollectionSpec]:
        collections: list[CollectionSpec] = []

        for knowledge in combined_surface.knowledge:
            collection_spec = self._build_collection_spec(knowledge)
            if collection_spec is not None:
                collections.append(collection_spec)

        return collections

    def _build_collection_spec(
        self, knowledge: CombinedSurfaceKnowledgeData
    ) -> CollectionSpec | None:
        collection_id = knowledge.collection
        search_configs = self._build_search_config_entries(collection_id, knowledge)
        if not search_configs:
            logger.warning(
                "Collection {} has no usable RAG search config, skipping.",
                collection_id,
            )
            return None

        collection = SourceCollection.objects.filter(pk=collection_id).first()
        if collection is None:
            logger.warning("SourceCollection {} not found, skipping.", collection_id)
            return None

        return CollectionSpec(
            unique_name=f"collection:{collection_id}",
            collection_id=collection_id,
            name=collection.collection_name,
            description=collection.description or None,
            search_configs=search_configs,
        )

    def _build_search_config_entries(
        self, collection_id: int, knowledge: CombinedSurfaceKnowledgeData
    ) -> list[SearchConfigEntry]:
        entries: list[SearchConfigEntry] = []

        if knowledge.naive_search_config is not None:
            entry = self._build_naive_search_config_entry(
                collection_id, knowledge.naive_search_config
            )
            if entry is not None:
                entries.append(entry)

        if (
            knowledge.graph_basic_search_config is not None
            or knowledge.graph_local_search_config is not None
            or knowledge.graph_global_search_config is not None
            or knowledge.graph_drift_search_config is not None
        ):
            entries.extend(
                self._build_graph_search_config_entries(collection_id, knowledge)
            )

        return entries

    def _build_naive_search_config_entry(
        self, collection_id: int, naive_config
    ) -> SearchConfigEntry | None:
        naive_rag = RagLookupService.latest_rag(
            NaiveRag, collection_id, pk_field="naive_rag_id"
        )
        if naive_rag is None:
            logger.warning(
                "No NaiveRag found for collection {}, skipping naive search config.",
                collection_id,
            )
            return None

        if naive_rag.embedder is None:
            logger.warning(
                "NaiveRag {} has no embedder configured, skipping.", naive_rag.pk
            )
            return None

        return SearchConfigEntry(
            rag_id=naive_rag.naive_rag_id,
            rag_type="naive",
            search_config=NaiveRagSearchConfig(
                search_limit=naive_config.search_limit,
                similarity_threshold=float(naive_config.similarity_threshold),
            ),
            embedder=self.converter_service.convert_embedding_config_to_pydantic(
                naive_rag.embedder
            ),
        )

    def _build_graph_search_config_entries(
        self, collection_id: int, knowledge: CombinedSurfaceKnowledgeData
    ) -> list[SearchConfigEntry]:
        graph_rag = RagLookupService.latest_rag(
            GraphRag, collection_id, pk_field="graph_rag_id"
        )
        if graph_rag is None:
            logger.warning(
                "No GraphRag found for collection {}, skipping graph search config.",
                collection_id,
            )
            return []

        if graph_rag.embedder is None:
            logger.warning(
                "GraphRag {} has no embedder configured, skipping.", graph_rag.pk
            )
            return []

        embedder = self.converter_service.convert_embedding_config_to_pydantic(
            graph_rag.embedder
        )
        entries: list[SearchConfigEntry] = []

        basic_config = knowledge.graph_basic_search_config
        if basic_config is not None:
            entries.append(
                SearchConfigEntry(
                    rag_id=graph_rag.graph_rag_id,
                    rag_type="graph",
                    search_config=GraphRagSearchConfig(
                        search_params=GraphRagBasicSearchParams(
                            prompt=basic_config.prompt,
                            k=basic_config.k,
                            max_context_tokens=basic_config.max_context_tokens,
                        )
                    ),
                    embedder=embedder,
                )
            )

        local_config = knowledge.graph_local_search_config
        if local_config is not None:
            entries.append(
                SearchConfigEntry(
                    rag_id=graph_rag.graph_rag_id,
                    rag_type="graph",
                    search_config=GraphRagSearchConfig(
                        search_params=GraphRagLocalSearchParams(
                            prompt=local_config.prompt,
                            text_unit_prop=local_config.text_unit_prop,
                            community_prop=local_config.community_prop,
                            conversation_history_max_turns=local_config.conversation_history_max_turns,
                            top_k_entities=local_config.top_k_entities,
                            top_k_relationships=local_config.top_k_relationships,
                            max_context_tokens=local_config.max_context_tokens,
                        )
                    ),
                    embedder=embedder,
                )
            )

        global_config = knowledge.graph_global_search_config
        if global_config is not None:
            entries.append(
                SearchConfigEntry(
                    rag_id=graph_rag.graph_rag_id,
                    rag_type="graph",
                    search_config=GraphRagSearchConfig(
                        search_params=GraphRagGlobalSearchParams(
                            **global_config.model_dump()
                        )
                    ),
                    embedder=embedder,
                )
            )

        drift_config = knowledge.graph_drift_search_config
        if drift_config is not None:
            entries.append(
                SearchConfigEntry(
                    rag_id=graph_rag.graph_rag_id,
                    rag_type="graph",
                    search_config=GraphRagSearchConfig(
                        search_params=GraphRagDriftSearchParams(
                            **drift_config.model_dump()
                        )
                    ),
                    embedder=embedder,
                )
            )

        return entries
