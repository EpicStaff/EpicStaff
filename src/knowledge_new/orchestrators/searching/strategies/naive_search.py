from errors import EmbeddingConfigNotFoundError
from loguru import logger
from models import NaiveSearchConfig, SearchRequest, SearchResponse
from orchestrators.searching.base import AbstractSearch
from services.embedders import build_embedder


class NaiveSearch(AbstractSearch):
    async def on_execute(self, request: SearchRequest) -> SearchResponse:
        # TODO: raise error if embedding config is different
        assert isinstance(request.search_config, NaiveSearchConfig)
        search_config = request.search_config

        async with self.uow:
            embedding_config = await self.uow.naive_rag_repo.get_embedding_config(
                rag_id=request.rag_id
            )

        if embedding_config is None:
            raise EmbeddingConfigNotFoundError(rag_id=request.rag_id)

        embedder = build_embedder(embedding_config.provider, embedding_config)
        vector = await embedder.embed(request.query)

        async with self.uow:
            chunks = await self.uow.naive_rag_repo.search_chunks(
                rag_id=request.rag_id,
                vector=vector,
                limit=search_config.search_limit,
                similarity_threshold=search_config.similarity_threshold,
            )

        logger.info("Search in rag {} returned {} chunks", request.rag_id, len(chunks))
        return SearchResponse(request=request, result=chunks)
