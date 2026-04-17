from typing import Dict, Optional, Type

from loguru import logger
from sqlalchemy.orm import Session, joinedload
from models.orm import NaiveRag, GraphRag, EmbeddingModel


class BaseORMStorage:
    """
    Base storage class for all RAG-specific storage implementations.

    Each RAG-specific storage (ORMNaiveRagStorage, ORMGraphRagStorage, etc.)
    inherits from this base class and implements RAG-specific operations.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_rag_table(self, rag_type: str) -> Type:
        """
        Get the appropriate RAG table class based on rag_type.
        """

        rag_tables = {
            "naive": NaiveRag,
            "graph": GraphRag,
        }

        rag_table = rag_tables.get(rag_type)
        if not rag_table:
            raise ValueError(
                f"Unsupported RAG type: '{rag_type}'. "
                f"Supported types: {list(rag_tables.keys())}"
            )

        return rag_table

    def get_embedder_configuration(
        self, rag_id: int, rag_type: str
    ) -> Dict[str, Optional[str]]:
        """
        Get embedder configuration for any RAG type.
        """

        try:
            rag_table = self.get_rag_table(rag_type)

            rag_instance = (
                self.session.query(rag_table)
                .options(joinedload(rag_table.embedder))
                .filter(getattr(rag_table, f"{rag_type}_rag_id") == rag_id)
                .one_or_none()
            )

            if rag_instance is None:
                raise ValueError(
                    f"{rag_type.capitalize()}Rag with id={rag_id} was not found"
                )

            if rag_instance.embedder is None:
                raise ValueError(
                    f"No embedding model found for {rag_type}_rag_id={rag_id}"
                )

            # Get embedder config with model and provider
            embedder = rag_instance.embedder
            model = (
                self.session.query(EmbeddingModel)
                .options(joinedload(EmbeddingModel.embedding_provider))
                .filter(EmbeddingModel.id == embedder.model_id)
                .one_or_none()
            )

            if not model or not model.embedding_provider:
                raise ValueError(
                    f"Invalid embedder configuration for {rag_type}_rag_id={rag_id}"
                )

            return {
                "api_key": getattr(embedder, "api_key", None),
                "model_name": model.name,
                "provider": model.embedding_provider.name,
            }

        except Exception as e:
            logger.error(
                f"Failed to get embedder configuration for {rag_type}_rag_id={rag_id}: {e}"
            )
            raise

    def get_base_rag_type(self, rag_id: int, rag_type: str):
        """
        Get BaseRagType record for any RAG implementation.
        """

        try:
            rag_table = self.get_rag_table(rag_type)

            rag_instance = (
                self.session.query(rag_table)
                .options(joinedload(rag_table.base_rag_type))
                .filter(getattr(rag_table, f"{rag_type}_rag_id") == rag_id)
                .one_or_none()
            )

            return rag_instance.base_rag_type if rag_instance else None

        except Exception as e:
            logger.error(
                f"Failed to get BaseRagType for {rag_type}_rag_id={rag_id}: {e}"
            )
            return None
