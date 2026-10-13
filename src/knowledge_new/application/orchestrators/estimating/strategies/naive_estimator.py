from application.commands import GetIndexEstimate
from application.orchestrators.estimating.base import AbstractEstimateOrchestrator
from application.results import EmbeddingEstimate, IndexEstimateResult
from domain.enums import DocumentStatusEnum, RAGStrategy
from domain.errors import (
    DocumentNotFoundError,
    EmbeddingConfigNotFoundError,
    RagNotFoundError,
)
from domain.models import Document
from infrastructure.file_text_extractors import build_file_text_extractor
from infrastructure.naive.chunkers import build_chunker
from infrastructure.token_estimation import (
    count_tokens_batch,
    has_exact_tokenizer,
    price_per_token,
    qualified_model_name,
)
from loguru import logger


class NaiveEstimateOrchestrator(AbstractEstimateOrchestrator):
    async def on_execute(self, command: GetIndexEstimate) -> IndexEstimateResult:
        async with self.uow:
            rag = await self.uow.naive_rag_repo.get_rag(rag_id=command.rag_id)
            if rag is None:
                raise RagNotFoundError(rag_id=command.rag_id)
            embedding_config = await self.uow.naive_rag_repo.get_embedding_config(rag_id=rag.id)
            if embedding_config is None:
                raise EmbeddingConfigNotFoundError(rag_id=rag.id)
            documents = await self.uow.naive_rag_repo.get_documents(
                rag_id=rag.id, ids=command.document_ids
            )
        if not documents:
            raise DocumentNotFoundError(f"No Document found for RAG(id={rag.id}).")

        pending_documents = [d for d in documents if self._will_be_indexed(d)]
        chunk_texts: list[str] = []
        indexed_document_count = 0
        for document in pending_documents:
            document_chunk_texts = await self._chunk_texts(document)
            if document_chunk_texts:
                indexed_document_count += 1
                chunk_texts += document_chunk_texts

        model = qualified_model_name(embedding_config.provider, embedding_config.model)
        # The embedder replaces newlines with spaces before sending; count what it sends.
        tokens = sum(
            await count_tokens_batch(model, [text.replace("\n", " ") for text in chunk_texts])
        )
        prices = price_per_token(model)
        return IndexEstimateResult(
            rag_type=RAGStrategy.NAIVE,
            document_count=indexed_document_count,
            chunk_count=len(chunk_texts),
            embedding=EmbeddingEstimate(
                tokens=tokens,
                exact=has_exact_tokenizer(embedding_config.provider),
                cost_usd=None if prices is None else tokens * prices[0],
            ),
        )

    @staticmethod
    def _will_be_indexed(document: Document) -> bool:
        """Mirror the skip rule of `NaiveIndexOrchestrator`: indexed with the same config."""
        return not (
            document.status == DocumentStatusEnum.COMPLETED and not document.has_config_changed()
        )

    @staticmethod
    async def _chunk_texts(document: Document) -> list[str]:
        """Return the chunk texts the indexer would embed, without persisting anything.

        Stored preview chunks win, as in the indexer; otherwise the document is chunked
        in memory. A document that cannot be read or chunked contributes nothing, since
        the indexer would mark it failed rather than embed it.
        """
        if document.preview_chunks and not document.has_config_changed():
            return [chunk.text for chunk in document.preview_chunks]
        try:
            extractor = build_file_text_extractor(document.extension)
            text = await extractor.extract(document.content)
            chunker = build_chunker(document.config.chunk_strategy, document.config)
            return [chunk.text for chunk in await chunker.chunk(text)]
        except Exception as error:
            # Mirror the indexer, which fails one bad document instead of the whole run.
            logger.warning("Skipped document(id={}) in index estimate: {}", document.id, error)
            return []
