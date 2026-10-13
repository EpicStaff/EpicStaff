from application.commands import RunSearch
from application.orchestrators.searching.base import AbstractSearchOrchestrator
from application.results import SearchResult
from domain.errors import EmbeddingConfigNotFoundError
from domain.models import NaiveSearchConfig, SearchUsage
from infrastructure.naive.embedders import build_embedder
from infrastructure.token_estimation import qualified_model_name
from infrastructure.usage_cost import embedding_cost
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

        embedding_config = embedding_config.model_copy(
            update={"extra_headers": command.embedding_extra_headers}
        )
        embedder = build_embedder(
            embedding_config.provider, command.embedding_api_key, embedding_config
        )
        embedding = await embedder.embed(command.query)

        async with self.uow:
            chunks = await self.uow.naive_rag_repo.search_chunks(
                rag_id=command.rag_id,
                vector=embedding.vector,
                limit=search_config.search_limit,
                similarity_threshold=search_config.similarity_threshold,
            )

        logger.info("Search in rag {} returned {} chunks", command.rag_id, len(chunks))
        usage = SearchUsage(
            embedding_tokens=embedding.tokens,
            embedding_cost_usd=embedding_cost(
                qualified_model_name(embedding_config.provider, embedding_config.model),
                embedding.tokens,
            ),
        )
        return SearchResult(result=chunks, usage=usage)
