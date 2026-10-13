from typing import cast

from application.commands import RunIndex
from application.orchestrators.indexing.base import AbstractIndexOrchestrator
from application.ports import AbstractEmbedder
from common.utils import utcnow
from domain.enums import DocumentStatusEnum, IndexStatusEnum
from domain.errors import (
    ChunksNotIndexedError,
    DocumentNotFoundError,
    EmbeddingConfigNotFoundError,
    NoPreviewChunksProducedError,
    RagNotFoundError,
    RepositoryError,
)
from domain.models import Document, IndexedChunk, Rag
from domain.usage import IndexingRunUsage, UsageTally
from infrastructure.file_text_extractors import build_file_text_extractor
from infrastructure.naive.chunkers import build_chunker
from infrastructure.naive.embedders import build_embedder
from infrastructure.token_estimation import qualified_model_name
from infrastructure.usage_cost import embedding_cost
from loguru import logger


class NaiveIndexOrchestrator(AbstractIndexOrchestrator):
    async def on_execute(self, command: RunIndex) -> None:
        async with self.uow:
            rag = await self._get_rag_under_uow(command.rag_id)
            embedder = await self._get_embedder_under_uow(
                rag.id, command.embedding_api_key, command.embedding_extra_headers
            )
            documents = await self._get_documents_under_uow(rag.id, command.document_ids)

        rag.mark_as_processing(command.document_ids)
        await self._update_rag(rag)

        usage = self.state["usage"] = UsageTally()
        for document in documents:
            if (
                document.status == DocumentStatusEnum.COMPLETED
                and not document.has_config_changed()
            ):
                logger.debug(
                    "Skipped indexing document(id={}) in RAG(id={}): "
                    "already indexed with the same config.",
                    document.id,
                    rag.id,
                )
                rag.finish_document(document.id)
                await self._update_rag(rag)
                continue

            self.state["processing_document"] = document
            self.state["processing_document_status"] = document.status
            document.mark_as_processing()
            await self._update_document(rag.id, document)

            try:
                if not document.preview_chunks or document.has_config_changed():
                    extractor = build_file_text_extractor(document.extension)
                    text = await extractor.extract(document.content)

                    chuncker = build_chunker(document.config.chunk_strategy, document.config)
                    preview_chunks = await chuncker.chunk(text)
                    if not preview_chunks:
                        raise NoPreviewChunksProducedError(
                            document_id=document.id,
                            rag_id=rag.id,
                        )
                    document.preview_chunks = preview_chunks

                # TODO: embed batch of chunks instead of one per time.
                indexed_chunks = []
                for preview_chunk in document.preview_chunks:
                    embedding = await embedder.embed(preview_chunk.text)
                    usage.embedding_tokens += embedding.tokens
                    indexed_chunks.append(
                        IndexedChunk(**preview_chunk.model_dump(), vector=embedding.vector)
                    )
                if not indexed_chunks:
                    raise ChunksNotIndexedError(document_id=document.id, rag_id=rag.id)

            except RepositoryError:
                raise

            except Exception as e:
                document.mark_as_failed(e)
                logger.exception(
                    "Failed indexing document(id={}) in RAG(id={}): {}",
                    document.id,
                    rag.id,
                    e,
                )
            else:
                document.mark_as_completed(indexed_chunks)
                logger.debug(
                    "Indexed document(id={}) in RAG(id={}): produced {} chunks.",
                    document.id,
                    rag.id,
                    len(document.indexed_chunks),
                )

            await self._finish_document(rag, document)

        await self._record_usage(rag.id)
        await self._finish_rag(rag)
        logger.info("Finished indexing in RAG(id={}, status={})", rag.id, rag.status.value)

    async def on_cancel(self, command: RunIndex):
        if (
            document := self.state.get("processing_document")
        ) is not None and document.status == DocumentStatusEnum.PROCESSING:
            document: Document
            document.status = self.state["processing_document_status"]
            await self._update_document(command.rag_id, document)

        if (rag := self.state.get("rag")) is not None:
            rag = cast(Rag, rag)
            rag.mark_as_cancelled()
            rag.finish_document(*command.document_ids)
            await self._update_rag(rag)
            await self._record_usage(rag.id)

    async def on_error(self, command: RunIndex, error: Exception):
        if (
            document := self.state.get("processing_document")
        ) is not None and document.status == DocumentStatusEnum.PROCESSING:
            document: Document
            document.status = self.state["processing_document_status"]
            await self._update_document(command.rag_id, document)

        if (rag := self.state.get("rag")) is not None:
            rag = cast(Rag, rag)
            rag.mark_as_failed(error)
            rag.finish_document(*command.document_ids)
            await self._update_rag(rag)
            await self._record_usage(rag.id)

    async def _get_rag_under_uow(self, rag_id: int) -> Rag:
        rag = await self.uow.naive_rag_repo.get_rag(rag_id=rag_id)
        if rag is None:
            raise RagNotFoundError(rag_id=rag_id)
        self.state["rag"] = rag
        return rag

    async def _get_embedder_under_uow(
        self, rag_id: int, api_key: str, extra_headers: dict[str, str]
    ) -> AbstractEmbedder:
        embedding_config = await self.uow.naive_rag_repo.get_embedding_config(rag_id=rag_id)
        if embedding_config is None:
            raise EmbeddingConfigNotFoundError(rag_id=rag_id)
        embedding_config = embedding_config.model_copy(update={"extra_headers": extra_headers})
        self.state["embedding_model"] = qualified_model_name(
            embedding_config.provider, embedding_config.model
        )
        return build_embedder(embedding_config.provider, api_key, embedding_config)

    async def _get_documents_under_uow(self, rag_id: int, ids: frozenset[int]) -> list[Document]:
        documents = await self.uow.naive_rag_repo.get_documents(rag_id=rag_id, ids=ids)

        if not documents:
            raise DocumentNotFoundError(f"No Document found for RAG(id={rag_id}).")
        return documents

    async def _record_usage(self, rag_id: int):
        """Store what the run consumed on the RAG, once per run.

        A failure to store is logged, not raised: the index itself already succeeded
        or failed on its own terms, and usage is reporting only.
        """
        tally: UsageTally | None = self.state.pop("usage", None)
        if tally is None or tally.is_empty:
            return
        run = IndexingRunUsage(
            embedding_tokens=tally.embedding_tokens,
            llm_input_tokens=None,
            llm_output_tokens=None,
            cost_usd=embedding_cost(self.state["embedding_model"], tally.embedding_tokens),
            completed_at=utcnow(),
        )
        try:
            async with self.uow:
                await self.uow.naive_rag_repo.add_indexing_usage(rag_id=rag_id, run=run)
                await self.uow.commit()
        except RepositoryError as error:
            logger.warning("Could not store indexing usage of RAG(id={}): {}", rag_id, error)

    async def _update_rag(self, rag: Rag):
        async with self.uow:
            await self.uow.naive_rag_repo.update_rag(rag=rag)
            await self.uow.commit()

    async def _update_document(self, rag_id: int, document: Document):
        async with self.uow:
            await self.uow.naive_rag_repo.update_document(rag_id=rag_id, document=document)
            await self.uow.commit()

    async def _finish_document(self, rag: Rag, document: Document):
        async with self.uow:
            await self.uow.naive_rag_repo.update_document(rag_id=rag.id, document=document)
            if document.status == DocumentStatusEnum.COMPLETED:
                await self.uow.naive_rag_repo.save_indexed_chunks(
                    document_id=document.id,
                    chunks=document.indexed_chunks,
                )
            rag.finish_document(document.id)
            await self.uow.naive_rag_repo.update_rag(rag=rag)
            await self.uow.commit()

    async def _finish_rag(self, rag: Rag):
        async with self.uow:
            has_outdated = await self.uow.naive_rag_repo.has_outdated_document(rag_id=rag.id)
            has_completed = await self.uow.naive_rag_repo.has_completed_document(rag_id=rag.id)
            has_failed = await self.uow.naive_rag_repo.has_failed_document(rag_id=rag.id)

            if has_outdated:
                rag.mark_as_outdated()
            elif rag.indexing_document_ids:
                rag.status = IndexStatusEnum.PROCESSING
            elif has_completed and has_failed:
                rag.mark_as_partial()
            elif has_completed:
                rag.mark_as_completed()
            elif has_failed:
                rag.mark_as_failed("Failed to index all documents.")
            else:
                rag.mark_as_new()

            if not has_outdated:
                rag.outdated_reasons.clear()

            await self.uow.naive_rag_repo.update_rag(rag=rag)
            await self.uow.commit()
