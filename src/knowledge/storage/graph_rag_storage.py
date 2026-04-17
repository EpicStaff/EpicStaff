from typing import List, Optional, Dict, Any
from sqlalchemy.orm import joinedload, selectinload
from loguru import logger

from .base_storage import BaseORMStorage
from models.orm import (
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    LLMModel,
    LLMConfig,
    EmbeddingModel,
    DocumentMetadata,
    DocumentContent,
)


class ORMGraphRagStorage(BaseORMStorage):
    """
    Storage implementation for GraphRag operations.

    All methods work with graph_rag_id.
    Inherits shared functionality from BaseORMStorage.
    """

    # ==================== GraphRag Operations ====================

    def get_graph_rag_by_id(self, graph_rag_id: int) -> Optional[GraphRag]:
        """
        Get GraphRag instance by ID with eager-loaded relationships.

        Args:
            graph_rag_id: ID of the GraphRag

        Returns:
            GraphRag instance or None if not found
        """
        try:
            return (
                self.session.query(GraphRag)
                .options(
                    joinedload(GraphRag.embedder),
                    joinedload(GraphRag.llm),
                    joinedload(GraphRag.index_config),
                    joinedload(GraphRag.base_rag_type),
                )
                .filter(GraphRag.graph_rag_id == graph_rag_id)
                .one_or_none()
            )
        except Exception as e:
            logger.error(f"Failed to get GraphRag {graph_rag_id}: {e}")
            return None

    def update_rag_status(self, graph_rag_id: int, status: str) -> bool:
        """
        Update the status of a GraphRag.

        Args:
            graph_rag_id: ID of the GraphRag
            status: New status (new, processing, completed, warning, failed)

        Returns:
            True if successful, False otherwise
        """
        try:
            graph_rag = self.session.get(GraphRag, graph_rag_id)
            if not graph_rag:
                logger.warning(f"GraphRag {graph_rag_id} not found")
                return False

            graph_rag.rag_status = status
            return True

        except Exception as e:
            logger.error(f"Failed to update GraphRag {graph_rag_id} status: {e}")
            return False

    def set_error_message(self, graph_rag_id: int, error_message: str) -> bool:
        """
        Set error message for a GraphRag.

        Args:
            graph_rag_id: ID of the GraphRag
            error_message: Error message to set

        Returns:
            True if successful, False otherwise
        """
        try:
            graph_rag = self.session.get(GraphRag, graph_rag_id)
            if not graph_rag:
                logger.warning(f"GraphRag {graph_rag_id} not found")
                return False

            graph_rag.error_message = error_message
            return True

        except Exception as e:
            logger.error(
                f"Failed to set error message for GraphRag {graph_rag_id}: {e}"
            )
            return False

    def set_indexed_at(self, graph_rag_id: int) -> bool:
        """
        Set indexed_at timestamp to now for a GraphRag.

        Args:
            graph_rag_id: ID of the GraphRag

        Returns:
            True if successful, False otherwise
        """
        from datetime import datetime

        try:
            graph_rag = self.session.get(GraphRag, graph_rag_id)
            if not graph_rag:
                logger.warning(f"GraphRag {graph_rag_id} not found")
                return False

            graph_rag.indexed_at = datetime.utcnow()
            return True

        except Exception as e:
            logger.error(f"Failed to set indexed_at for GraphRag {graph_rag_id}: {e}")
            return False

    # ==================== Document Operations ====================

    def get_graph_rag_documents(self, graph_rag_id: int) -> List[GraphRagDocument]:
        """
        Get all documents linked to a GraphRag.

        Args:
            graph_rag_id: ID of the GraphRag

        Returns:
            List of GraphRagDocument instances with document metadata loaded
        """
        try:
            return (
                self.session.query(GraphRagDocument)
                .options(
                    selectinload(GraphRagDocument.document).selectinload(
                        DocumentMetadata.document_content
                    )
                )
                .filter(GraphRagDocument.graph_rag_id == graph_rag_id)
                .all()
            )

        except Exception as e:
            logger.error(f"Failed to get documents for GraphRag {graph_rag_id}: {e}")
            return []

    def get_graph_rag_document_by_id(
        self, graph_rag_document_id: int
    ) -> Optional[GraphRagDocument]:
        """
        Get a specific GraphRagDocument by ID.

        Args:
            graph_rag_document_id: ID of the GraphRagDocument

        Returns:
            GraphRagDocument instance or None
        """
        try:
            return (
                self.session.query(GraphRagDocument)
                .options(
                    selectinload(GraphRagDocument.document).selectinload(
                        DocumentMetadata.document_content
                    )
                )
                .filter(GraphRagDocument.graph_rag_document_id == graph_rag_document_id)
                .one_or_none()
            )
        except Exception as e:
            logger.error(f"Failed to get GraphRagDocument {graph_rag_document_id}: {e}")
            return None

    # ==================== Configuration Operations ====================

    def get_index_config_dict(self, graph_rag_id: int) -> Optional[Dict[str, Any]]:
        """
        Get index configuration for a GraphRag as a dictionary.

        This method returns a dict to avoid SQLAlchemy detached instance issues
        when the config needs to be used outside the session context.

        Args:
            graph_rag_id: ID of the GraphRag

        Returns:
            Dict with index config parameters or None
        """
        try:
            graph_rag = self.get_graph_rag_by_id(graph_rag_id)
            if graph_rag and graph_rag.index_config:
                config = graph_rag.index_config
                return {
                    "file_type": config.file_type,
                    "chunk_size": config.chunk_size,
                    "chunk_overlap": config.chunk_overlap,
                    "chunk_strategy": config.chunk_strategy,
                    "entity_types": config.entity_types,
                    "max_gleanings": config.max_gleanings,
                    "max_cluster_size": config.max_cluster_size,
                }
            return None

        except Exception as e:
            logger.error(
                f"Failed to get index config dict for GraphRag {graph_rag_id}: {e}"
            )
            return None

    def get_embedder_configuration(self, graph_rag_id: int) -> Dict[str, Optional[str]]:
        """
        Get embedder configuration for a GraphRag.

        Args:
            graph_rag_id: ID of the GraphRag

        Returns:
            Dict with api_key, model_name, provider
        """
        try:
            graph_rag = (
                self.session.query(GraphRag)
                .options(joinedload(GraphRag.embedder))
                .filter(GraphRag.graph_rag_id == graph_rag_id)
                .one_or_none()
            )

            if graph_rag is None:
                raise ValueError(f"GraphRag with id={graph_rag_id} was not found")

            if graph_rag.embedder is None:
                raise ValueError(
                    f"No embedding config found for graph_rag_id={graph_rag_id}"
                )

            # Get embedder config with model and provider
            embedder = graph_rag.embedder
            model = (
                self.session.query(EmbeddingModel)
                .options(joinedload(EmbeddingModel.embedding_provider))
                .filter(EmbeddingModel.id == embedder.model_id)
                .one_or_none()
            )

            if not model or not model.embedding_provider:
                raise ValueError(
                    f"Invalid embedder configuration for graph_rag_id={graph_rag_id}"
                )

            return {
                "api_key": getattr(embedder, "api_key", None),
                "model_name": model.name,
                "provider": model.embedding_provider.name,
                "base_url": getattr(model, "base_url", None),
                "deployment": getattr(model, "deployment", None),
            }

        except Exception as e:
            logger.error(
                f"Failed to get embedder configuration for graph_rag_id={graph_rag_id}: {e}"
            )
            raise

    def get_llm_configuration(self, graph_rag_id: int) -> Dict[str, Any]:
        """
        Get LLM configuration for a GraphRag.

        Args:
            graph_rag_id: ID of the GraphRag

        Returns:
            Dict with all LLM configuration parameters
        """
        try:
            graph_rag = (
                self.session.query(GraphRag)
                .options(joinedload(GraphRag.llm).joinedload(LLMConfig.model))
                .filter(GraphRag.graph_rag_id == graph_rag_id)
                .one_or_none()
            )

            if graph_rag is None:
                raise ValueError(f"GraphRag with id={graph_rag_id} was not found")

            if graph_rag.llm is None:
                raise ValueError(f"No LLM config found for graph_rag_id={graph_rag_id}")

            llm_config = graph_rag.llm
            llm_model = llm_config.model

            # Get provider name
            provider_name = None
            if llm_model and llm_model.llm_provider_id:
                from models.orm import Provider

                provider = self.session.get(Provider, llm_model.llm_provider_id)
                provider_name = provider.name if provider else None

            return {
                "api_key": llm_config.api_key,
                "model_name": llm_model.name if llm_model else None,
                "provider": provider_name,
                "base_url": llm_model.base_url if llm_model else None,
                "deployment": llm_model.deployment_id if llm_model else None,
                "api_version": llm_model.api_version if llm_model else None,
                "temperature": llm_config.temperature,
                "top_p": llm_config.top_p,
                "max_tokens": llm_config.max_tokens,
                "timeout": llm_config.timeout,
                "stop": llm_config.stop,
                "presence_penalty": llm_config.presence_penalty,
                "frequency_penalty": llm_config.frequency_penalty,
            }

        except Exception as e:
            logger.error(
                f"Failed to get LLM configuration for graph_rag_id={graph_rag_id}: {e}"
            )
            raise
