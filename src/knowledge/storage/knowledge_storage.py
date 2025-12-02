from typing import Dict, Optional, List
from sqlalchemy.orm import joinedload
from sqlalchemy import delete, select
from loguru import logger

from .base_storage import BaseORMStorage
from models.orm.document_models import (
    DocumentEmbedding,
    EmbeddingModel,
    Provider,
    SourceCollection,
    EmbeddingConfig,
    DocumentMetadata,
    Chunk,
)
from models.enums import *
from models.dto.models_dto import KnowledgeChunkDTO
from sqlalchemy.orm import Session


class ORMKnowledgeStorage(BaseORMStorage):

    def save_embedding(
        self,
        chunk_id: int,
        embedding: list[float],
        document_id: int,
        collection_id: int,
    ) -> None:
        """Insert a new embedding using ORM."""
        try:
            embedding_obj = DocumentEmbedding(
                chunk_id=chunk_id,
                vector=embedding,
                document_id=document_id,
                collection_id=collection_id,
            )
            self.session.add(embedding_obj)
        except Exception as e:
            logger.error(f"Failed to save embedding: {e}")
            raise

    def delete_document_embeddings(self, document_id: int) -> None:
        stmt = delete(DocumentEmbedding).where(
            DocumentEmbedding.document_id == document_id
        )
        self.session.execute(stmt)

    def update_collection_status(self, status: Status, collection_id: int) -> bool:
        """Update the status of a collection."""
        if status not in Status:
            logger.error(f"Trying to set an invalid status: {status}")
            return False

        try:
            collection = self.session.get(SourceCollection, collection_id)
            if not collection:
                logger.warning(f"Collection {collection_id} not found")
                return False
            collection.status = status
            return True
        except Exception as e:
            logger.error(f"Failed to update collection {collection_id}: {e}")
            return False

    def get_embedder_configuration(
        self, collection_id: int
    ) -> Dict[str, Optional[str]]:
        """Get embedding configuration for a collection."""
        try:
            collection = (
                self.session.query(SourceCollection)
                .options(joinedload(SourceCollection.embedder))
                .filter(SourceCollection.collection_id == collection_id)
                .one_or_none()
            )
            if collection is None:
                raise ValueError(
                    f"Collection with collection_id={collection_id} was not found"
                )
            if collection.embedder is None:
                raise ValueError(
                    f"No embedding model found for collection_id={collection_id}"
                )

            embedder: EmbeddingConfig = collection.embedder
            model: EmbeddingModel = embedder.model
            embedding_provider: Provider = model.embedding_provider
            return {
                "api_key": getattr(embedder, "api_key", None),
                "model_name": model.name,
                "provider": embedding_provider.name,
            }
        except Exception as e:
            logger.error(
                f"Failed to get embedder configuration for {collection_id}: {e}"
            )
            raise

    def search(
        self,
        embedded_query: List[float],
        collection_id: int,
        limit: int = 3,
        similarity_threshold: float = 0.2,
    ) -> list[KnowledgeChunkDTO]:
        """
        Search documents in the knowledge base using vector similarity.
        similarity_threshold: min similarity (0 = no similarity, 1 = identical)
        """
        try:
            # Compute distance = 1 - similarity
            similarity_expr = (
                1 - DocumentEmbedding.vector.cosine_distance(embedded_query)
            ).label("similarity")

            stmt = (
                select(Chunk.text, similarity_expr, DocumentMetadata.file_name)
                .join(Chunk, Chunk.id == DocumentEmbedding.chunk_id)
                .join(
                    DocumentMetadata,
                    DocumentMetadata.document_id == DocumentEmbedding.document_id,
                )
                .where(DocumentEmbedding.collection_id == collection_id)
                .order_by(similarity_expr.desc())  # safer
                .limit(limit)
            )
            results = self.session.execute(stmt).all()

            final_result = []
            for i, r in enumerate(results, start=1):
                similarity = r.similarity
                if similarity is not None and similarity >= similarity_threshold:
                    logger.info(f"Chunk #{i} (similarity: {similarity:.4f}): {r.text}")
                    chunk_data = KnowledgeChunkDTO(
                        chunk_order=i,
                        chunk_similarity=round(similarity, 4),
                        chunk_text=r.text,
                        chunk_source=r.file_name,
                    )
                    final_result.append(chunk_data)

            logger.info(
                f"Returning {len(final_result)} chunks (threshold={similarity_threshold})"
            )
            return final_result

        except Exception as e:
            logger.error(f"Search failed for collection {collection_id}: {e}")
            return []
