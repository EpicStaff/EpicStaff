from application.commands import RunSearch
from application.orchestrators.searching.base import AbstractSearchOrchestrator
from application.results import SearchResult
from domain.errors import EmbeddingConfigNotFoundError
from domain.models import NaiveSearchConfig
from infrastructure.naive.embedders import build_embedder
from loguru import logger


class NaiveSearchOrchestrator(AbstractSearchOrchestrator):
    async def on_execute(self, command: RunSearch) -> SearchResult:
        # TODO: raise error if embedding config is different
        assert isinstance(command.search_config, NaiveSearchConfig)
        search_config = command.search_config

        async with self.uow:
            embedding_config = await self.uow.naive_rag_repo.get_embedding_config(
                rag_id=command.rag_id
            )

        if embedding_config is None:
            raise EmbeddingConfigNotFoundError(rag_id=command.rag_id)

        embedder = build_embedder(embedding_config.provider, embedding_config)
        vector = await embedder.embed(command.query)

        async with self.uow:
            chunks = await self.uow.naive_rag_repo.search_chunks(
                rag_id=command.rag_id,
                vector=vector,
                limit=search_config.search_limit,
                similarity_threshold=search_config.similarity_threshold,
            )

        logger.info("Search in rag {} returned {} chunks", command.rag_id, len(chunks))
        return SearchResult(result=chunks)
