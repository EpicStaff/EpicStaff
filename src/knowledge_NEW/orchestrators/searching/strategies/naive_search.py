from loguru import logger

from errors import EmbedderUnavailableError
from models import (
    SearchRequest,
    SearchResponse,
    NaiveSearchConfig,
)
from database.unit_of_work import SQLAlchemyUnitOfWork
from orchestrators.searching.base import AbstractSearch
from services.embedders import build_embedder


class NaiveSearch(AbstractSearch):
    """Naive searcher that embeds the query and ranks chunks by similarity."""

    async def search(
        self, request: SearchRequest, uow: SQLAlchemyUnitOfWork
    ) -> SearchResponse:
        """Embed the query in `request` and return the most similar chunks.

        Args:
            request: Search request with the RAG, query, and search config.
            uow: Unit of work providing repository access.

        Returns:
            The chunks matching the query, ordered by descending similarity.

        Raises:
            EmbedderUnavailableError: If the RAG has no embedding config.
        """
        assert isinstance(request.search_config, NaiveSearchConfig)
        search_config = request.search_config

        logger.info(
            "Searching RAG(id={}) for up to {} chunks above similarity {}",
            request.rag_id,
            search_config.search_limit,
            search_config.similarity_threshold,
        )

        async with uow:
            embedding_config = await uow.naive_rag_repo.get_embedding_config(
                rag_id=request.rag_id
            )

        if embedding_config is None:
            logger.warning(
                "RAG(id={}) has no embedding config, cannot search", request.rag_id
            )
            raise EmbedderUnavailableError(
                f"No embedding config for rag_id={request.rag_id}"
            )

        embedder = build_embedder(embedding_config.provider, embedding_config)
        vector = await embedder.embed(request.query)

        async with uow:
            chunks = await uow.naive_rag_repo.search_chunks(
                rag_id=request.rag_id,
                vector=vector,
                limit=search_config.search_limit,
                similarity_threshold=search_config.similarity_threshold,
            )

        logger.info(
            "Search in RAG(id={}) returned {} chunks", request.rag_id, len(chunks)
        )

        return SearchResponse(request=request, chunks=chunks)
