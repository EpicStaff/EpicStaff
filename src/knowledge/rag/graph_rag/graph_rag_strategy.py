import asyncio
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from graphrag.api.index import build_index
from graphrag.api.query import basic_search, local_search
from graphrag.config.models.graph_rag_config import GraphRagConfig

from rag.base_rag_strategy import BaseRAGStrategy
from rag.graph_rag.graph_rag_file_manager import GraphRagFileManager
from rag.graph_rag.graph_rag_config_builder import GraphRagConfigBuilder
from src.shared.models import (
    GraphRagSearchConfig,
    BaseKnowledgeSearchMessageResponse,
    KnowledgeChunkResponse,
)
from settings import UnitOfWork


class GraphRAGStrategy(BaseRAGStrategy):
    """
    GraphRAG implementation strategy using Microsoft's graphrag library.

    Uses knowledge graphs for enhanced retrieval with entity extraction,
    relationship mapping, and community-based summarization.

    Components:
    - GraphRagFileManager: Handles all file/folder operations
    - GraphRagConfigBuilder: Builds GraphRagConfig from database settings
    - ORMGraphRagStorage: Handles database operations (via UnitOfWork)
    """

    RAG_TYPE = "graph"

    def __init__(self, base_dir: str | Path | None = None):
        """
        Initialize the GraphRAG strategy.

        Args:
            base_dir: Optional base directory for graph data storage.
                     Defaults to <project>/src/knowledge/graph_data
        """
        self.file_manager = GraphRagFileManager(base_dir=base_dir)
        self.config_builder = GraphRagConfigBuilder()

    # ==================== Indexing ====================

    def process_rag_indexing(self, rag_id: int):
        """
        Process RAG indexing for a GraphRag.

        Flow:
        1. Get configuration from database
        2. Create folder structure
        3. Load documents to input folder
        4. Build GraphRagConfig
        5. Run graphrag indexing
        6. Update status in database

        Args:
            rag_id: ID of the GraphRag (graph_rag_id)
        """
        graph_rag_id = rag_id
        uow = UnitOfWork()

        try:
            # Step 1: Get configurations and update status
            with uow.start() as uow_ctx:
                uow_ctx.graph_rag_storage.update_rag_status(
                    graph_rag_id=graph_rag_id,
                    status="processing",
                )
                logger.info(f"Processing indexing for graph_rag_id: {graph_rag_id}")

                # Get configurations
                graph_rag = uow_ctx.graph_rag_storage.get_graph_rag_by_id(graph_rag_id)
                if not graph_rag:
                    raise ValueError(f"GraphRag {graph_rag_id} not found")

                # Get index config as dict to avoid detached instance issues
                index_config = uow_ctx.graph_rag_storage.get_index_config_dict(
                    graph_rag_id
                )

                # Get LLM and embedder configs (already return dicts)
                llm_config = uow_ctx.graph_rag_storage.get_llm_configuration(
                    graph_rag_id
                )
                embedder_config = uow_ctx.graph_rag_storage.get_embedder_configuration(
                    graph_rag_id
                )

                # Get all documents linked to this GraphRag
                # Note: GraphRagDocument doesn't have status - we index all linked documents
                documents = uow_ctx.graph_rag_storage.get_graph_rag_documents(
                    graph_rag_id=graph_rag_id,
                )

                if not documents:
                    logger.warning(f"GraphRag {graph_rag_id} has no documents to index")
                    uow_ctx.graph_rag_storage.update_rag_status(
                        graph_rag_id=graph_rag_id,
                        status="warning",
                    )
                    return

            # Step 2: Create folder structure
            root_folder = self.file_manager.get_or_create_root_folder(graph_rag_id)
            input_folder = self.file_manager.get_or_create_input_folder(root_folder)

            # Step 3: Load documents to input folder
            with uow.start() as uow_ctx:
                documents = uow_ctx.graph_rag_storage.get_graph_rag_documents(
                    graph_rag_id=graph_rag_id,
                )
                loaded_files = self.file_manager.load_documents_to_input(
                    graph_rag_documents=documents,
                    input_folder=input_folder,
                )

            if not loaded_files:
                raise ValueError("No documents were loaded to input folder")

            # Step 4: Setup environment with API key
            api_key = llm_config.get("api_key") or embedder_config.get("api_key")
            if api_key:
                self.file_manager.setup_env_file(
                    root_folder=root_folder,
                    api_key=api_key,
                )

            # Step 5: Build GraphRagConfig
            graphrag_config = self.config_builder.build_config(
                root_folder=root_folder,
                llm_config=llm_config,
                embedder_config=embedder_config,
                index_config=index_config,
            )

            # Step 6: Run graphrag indexing
            logger.info(f"Starting GraphRAG indexing for graph_rag_id: {graph_rag_id}")
            self._run_indexing(graphrag_config)
            logger.success(
                f"GraphRAG indexing completed for graph_rag_id: {graph_rag_id}"
            )

            # Step 6.5: Persist GraphRagConfig for fast search restore
            self.file_manager.save_config(root_folder, graphrag_config)

            # Step 7: Update GraphRag status to completed
            with uow.start() as uow_ctx:
                uow_ctx.graph_rag_storage.update_rag_status(
                    graph_rag_id=graph_rag_id,
                    status="completed",
                )
                uow_ctx.graph_rag_storage.set_indexed_at(graph_rag_id)

            # TODO: handle cleaning
            # self.file_manager.clean_input_folder(input_folder)

        except Exception as e:
            logger.error(f"Error processing graph_rag_id {graph_rag_id}: {e}")
            with uow.start() as uow_ctx:
                uow_ctx.graph_rag_storage.update_rag_status(
                    graph_rag_id=graph_rag_id,
                    status="failed",
                )
                uow_ctx.graph_rag_storage.set_error_message(
                    graph_rag_id=graph_rag_id,
                    error_message=str(e),
                )
            raise

    def _run_indexing(self, config: GraphRagConfig) -> None:
        """
        Run the GraphRAG indexing pipeline.

        Args:
            config: GraphRagConfig instance
        """
        # GraphRAG's build_index is async
        asyncio.run(build_index(config))

    # ==================== Search ====================

    def search(
        self,
        rag_id: int,
        uuid: str,
        query: str,
        collection_id: int,
        rag_search_config: GraphRagSearchConfig,
    ) -> dict:
        """
        Search using GraphRAG. Dispatches to basic or local search
        based on rag_search_config.search_method.

        Loads persisted GraphRagConfig from file (no DB calls) and applies
        search params from the Redis message.

        Args:
            rag_id: ID of the GraphRag (graph_rag_id)
            uuid: Request UUID
            query: Search query
            collection_id: Collection ID (for response)
            rag_search_config: Search configuration with search_method

        Returns:
            Dict with search results
        """
        graph_rag_id = rag_id
        token_usage = {}
        search_params = rag_search_config.search_params
        search_method = search_params.search_method

        try:
            # Step 1: Check if index exists
            if not self.file_manager.index_exists(graph_rag_id):
                logger.warning(f"No index found for graph_rag_id: {graph_rag_id}")
                return self._build_empty_response(
                    graph_rag_id=graph_rag_id,
                    collection_id=collection_id,
                    uuid=uuid,
                    query=query,
                    rag_search_config=rag_search_config,
                    error="Index not found",
                )

            # Step 2: Load persisted config from file (no DB calls)
            root_folder = self.file_manager.get_root_folder_path(graph_rag_id)
            graphrag_config = self.file_manager.load_config(root_folder)

            # Step 3: Apply search params from Redis message
            if search_method == "local":
                self.config_builder.apply_local_search_params(
                    graphrag_config, search_params
                )
            else:
                self.config_builder.apply_basic_search_params(
                    graphrag_config, search_params
                )

            # Step 4: Execute search
            if search_method == "local":
                logger.info(f"Running local search for graph_rag_id: {graph_rag_id}")
                response, context = self._run_local_search(
                    root_folder=root_folder,
                    graphrag_config=graphrag_config,
                    query=query,
                )
            else:
                logger.info(f"Running basic search for graph_rag_id: {graph_rag_id}")
                response, context = self._run_basic_search(
                    root_folder=root_folder,
                    graphrag_config=graphrag_config,
                    query=query,
                )

            # Step 5: Build response with single-chunk extraction
            knowledge_chunks = self._extract_chunks_from_context(
                response, search_method
            )
            knowledge_snippets = [chunk.chunk_text for chunk in knowledge_chunks]

            if knowledge_snippets:
                logger.info(f"QUERY: [{query}]")
                logger.info(f"RESULTS: {knowledge_snippets[0][:300]}...")
            else:
                logger.warning("No knowledge chunks extracted from search")

            result = BaseKnowledgeSearchMessageResponse(
                rag_id=graph_rag_id,
                rag_type=self.RAG_TYPE,
                collection_id=collection_id,
                uuid=uuid,
                retrieved_chunks=len(knowledge_chunks),
                query=query,
                chunks=knowledge_chunks,
                rag_search_config=rag_search_config,
                results=knowledge_snippets,
                token_usage=token_usage,
            )

            return result.model_dump()

        except Exception as e:
            logger.error(f"Search failed for graph_rag_id {graph_rag_id}: {e}")
            return self._build_empty_response(
                graph_rag_id=graph_rag_id,
                collection_id=collection_id,
                uuid=uuid,
                query=query,
                rag_search_config=rag_search_config,
                error=str(e),
            )

    def _run_basic_search(
        self,
        root_folder: Path,
        graphrag_config: GraphRagConfig,
        query: str,
    ) -> tuple:
        """Run basic search using text_units only."""
        text_units = self._load_parquet(root_folder, "text_units.parquet")
        return asyncio.run(
            basic_search(
                config=graphrag_config,
                text_units=text_units,
                query=query,
            )
        )

    def _run_local_search(
        self,
        root_folder: Path,
        graphrag_config: GraphRagConfig,
        query: str,
    ) -> tuple:
        """
        Run local search using entities, communities, community_reports,
        text_units, relationships, and optional covariates.
        """
        text_units = self._load_parquet(root_folder, "text_units.parquet")
        entities = self._load_parquet(root_folder, "entities.parquet")
        communities = self._load_parquet(root_folder, "communities.parquet")
        community_reports = self._load_parquet(root_folder, "community_reports.parquet")
        relationships = self._load_parquet(root_folder, "relationships.parquet")

        # Covariates are optional — not always produced by indexing
        covariates = None
        covariates_path = root_folder / "output" / "covariates.parquet"
        if covariates_path.exists():
            covariates = pd.read_parquet(covariates_path)

        return asyncio.run(
            local_search(
                config=graphrag_config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                text_units=text_units,
                relationships=relationships,
                covariates=covariates,
                community_level=2,
                response_type="Multiple Paragraphs",
                query=query,
            )
        )

    def _load_parquet(self, root_folder: Path, filename: str) -> pd.DataFrame:
        """Load a parquet file from the output directory."""
        file_path = root_folder / "output" / filename
        if not file_path.exists():
            raise FileNotFoundError(f"{filename} not found at {file_path}")
        return pd.read_parquet(file_path)

    def _extract_chunks_from_context(
        self,
        response,
        search_method: str,
    ) -> list[KnowledgeChunkResponse]:
        """
        Wrap the LLM response as a single knowledge chunk.

        Args:
            response: LLM response string from graphrag search
            search_method: "basic" or "local"

        Returns:
            List with a single KnowledgeChunkResponse
        """
        if not response:
            return []
        return [
            KnowledgeChunkResponse(
                chunk_order=1,
                chunk_similarity=1.0,
                chunk_text=str(response),
                chunk_source=f"graphrag_{search_method}_search",
            )
        ]

    def _build_empty_response(
        self,
        graph_rag_id: int,
        collection_id: int,
        uuid: str,
        query: str,
        rag_search_config: GraphRagSearchConfig,
        error: Optional[str] = None,
    ) -> dict:
        """Build an empty response for error cases."""
        result = BaseKnowledgeSearchMessageResponse(
            rag_id=graph_rag_id,
            rag_type=self.RAG_TYPE,
            collection_id=collection_id,
            uuid=uuid,
            retrieved_chunks=0,
            query=query,
            chunks=[],
            rag_search_config=rag_search_config,
            results=[],
            token_usage={"error": error} if error else {},
        )
        return result.model_dump()
