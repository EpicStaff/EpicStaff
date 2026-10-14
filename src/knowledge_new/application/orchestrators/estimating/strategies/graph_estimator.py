import math

from application.commands import GetIndexEstimate
from application.orchestrators.estimating.base import AbstractEstimateOrchestrator
from application.results import EmbeddingEstimate, IndexEstimateResult, LlmEstimate
from domain.enums import DocumentStatusEnum, IndexStatusEnum, RAGStrategy
from domain.errors import DocumentNotFoundError, GraphRagConfigNotFoundError, RagNotFoundError
from domain.models import GraphEstimateConfig, Rag
from graphrag.prompts.index.extract_graph import GRAPH_EXTRACTION_PROMPT
from graphrag_input import TextDocument
from infrastructure.token_estimation import (
    count_tokens_batch,
    has_exact_tokenizer,
    price_per_token,
    qualified_model_name,
)


class GraphEstimateOrchestrator(AbstractEstimateOrchestrator):
    """Estimate a GraphRAG index run.

    Embedding tokens cover the text chunks only; entity, relationship and community
    embeddings made later in the pipeline are not predictable up front, so the figure
    is a lower bound. The LLM figure is a range: every chunk is extracted once, and
    each gleaning pass (up to `max_gleanings`) adds one more call per chunk.
    """

    async def on_execute(self, command: GetIndexEstimate) -> IndexEstimateResult:
        async with self.uow:
            rag = await self.uow.graph_rag_repo.get_rag(rag_id=command.rag_id)
            if rag is None:
                raise RagNotFoundError(rag_id=command.rag_id)
            config = await self.uow.graph_rag_repo.get_estimate_config(rag_id=rag.id)
            if config is None:
                raise GraphRagConfigNotFoundError(rag_id=rag.id)
            if command.index_config is not None:
                config = command.index_config.apply_to(config)
            selected = await self.uow.graph_rag_repo.get_documents(
                rag_id=rag.id, ids=command.document_ids
            )
            if not selected:
                raise DocumentNotFoundError(f"No Document found for RAG(id={rag.id}).")
            documents = selected
            if self._is_reindex(rag, selected):
                documents = selected + (
                    await self.uow.graph_rag_repo.get_indexed_documents_excluding(
                        rag_id=rag.id, ids=command.document_ids
                    )
                )

        embedding_model = qualified_model_name(config.embedding.provider, config.embedding.model)
        chunk_count = 0
        chunk_tokens = 0
        document_token_counts = await count_tokens_batch(
            embedding_model, [document.text for document in documents]
        )
        for document_token_count in document_token_counts:
            document_chunks, document_tokens = self._chunk_stats(document_token_count, config)
            chunk_count += document_chunks
            chunk_tokens += document_tokens

        embedding_prices = price_per_token(embedding_model)
        return IndexEstimateResult(
            rag_type=RAGStrategy.GRAPH,
            document_count=len(documents),
            chunk_count=chunk_count,
            embedding=EmbeddingEstimate(
                tokens=chunk_tokens,
                exact=has_exact_tokenizer(config.embedding.provider),
                cost_usd=None if embedding_prices is None else chunk_tokens * embedding_prices[0],
            ),
            llm=await self._estimate_llm(config, chunk_count, chunk_tokens),
        )

    @staticmethod
    def _is_reindex(rag: Rag, selected: list[TextDocument]) -> bool:
        """Mirror `GraphIndexOrchestrator`: re-indexing a finished index rebuilds all documents."""
        return rag.status == IndexStatusEnum.COMPLETED and any(
            d.raw_data["status"] == DocumentStatusEnum.COMPLETED for d in selected
        )

    @staticmethod
    def _chunk_stats(document_tokens: int, config: GraphEstimateConfig) -> tuple[int, int]:
        """Return `(chunks, total chunk tokens)` of a token-window split with overlap."""
        if document_tokens == 0:
            return 0, 0
        if document_tokens <= config.chunk_size:
            return 1, document_tokens
        stride = max(config.chunk_size - config.chunk_overlap, 1)
        chunks = math.ceil((document_tokens - config.chunk_overlap) / stride)
        return chunks, document_tokens + config.chunk_overlap * (chunks - 1)

    async def _estimate_llm(
        self, config: GraphEstimateConfig, chunk_count: int, chunk_tokens: int
    ) -> LlmEstimate:
        """Estimate extraction calls, tokens and cost.

        Per call the prompt is the extraction template plus one chunk; the completion
        is assumed to be about one chunk long, since extraction output scales with
        the text it summarizes.
        """
        llm_model = qualified_model_name(config.llm_provider, config.llm_model)
        (prompt_overhead,) = await count_tokens_batch(llm_model, [GRAPH_EXTRACTION_PROMPT])
        input_tokens = chunk_tokens + chunk_count * prompt_overhead
        output_tokens = chunk_tokens
        passes = 1 + config.max_gleanings
        prices = self._llm_prices(config, llm_model)

        def cost(multiplier: int) -> float | None:
            if prices is None:
                return None
            return multiplier * (input_tokens * prices[0] + output_tokens * prices[1])

        return LlmEstimate(
            calls=chunk_count * passes,
            tokens_min=input_tokens + output_tokens,
            tokens_max=(input_tokens + output_tokens) * passes,
            cost_usd_min=cost(1),
            cost_usd_max=cost(passes),
        )

    @staticmethod
    def _llm_prices(config: GraphEstimateConfig, llm_model: str) -> tuple[float, float] | None:
        """Prefer the LLM config's own prices, then litellm's price map."""
        if config.input_cost_per_token is not None and config.output_cost_per_token is not None:
            return config.input_cost_per_token, config.output_cost_per_token
        return price_per_token(llm_model)
