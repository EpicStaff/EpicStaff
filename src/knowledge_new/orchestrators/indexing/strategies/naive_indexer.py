from typing import cast

from enums import DocumentStatusEnum
from errors import (
    ChunksNotIndexedError,
    DocumentNotFoundError,
    EmbeddingConfigNotFoundError,
    NoPreviewChunksProducedError,
    RagNotFoundError,
    RepositoryError,
)
from loguru import logger
from models import Document, IndexedChunk, IndexRequest, Rag
from orchestrators.indexing import AbstractIndexer
from services.chunkers import build_chunker
from services.embedders import AbstractEmbedder, build_embedder
from services.file_text_extractors import build_file_text_extractor


class NaiveIndexer(AbstractIndexer):
    async def on_execute(self, request: IndexRequest) -> None:
        async with self.uow:
            rag = await self._get_rag_under_uow(request.rag_id)
            embedder = await self._get_embedder_under_uow(rag.id)
            documents = await self._get_documents_under_uow(rag.id, request.document_ids)

        rag.mark_as_processing(request.document_ids)
        await self._update_rag(rag)

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

            document.mark_as_processing()
            await self._update_document(rag.id, document)

            try:
                if not document.preview_chunks or document.has_config_changed():
                    document.mark_as_chunking()
                    await self._update_document(rag.id, document)

                    extractor = build_file_text_extractor(document.extension)
                    text = await extractor.extract(document.content)

                    chuncker = build_chunker(document.config.chunk_strategy, document.config)
                    preview_chunks = await chuncker.chunk(text)
                    if not preview_chunks:
                        raise NoPreviewChunksProducedError(
                            document_id=document.id,
                            rag_id=rag.id,
                        )
                    document.mark_as_chunked(preview_chunks)
                    await self._update_document(rag.id, document)

                document.mark_as_indexing()
                await self._update_document(rag.id, document)
                # TODO: embed batch of chunks instead of one per time.
                indexed_chunks = [
                    IndexedChunk(
                        **ph.model_dump(),
                        vector=await embedder.embed(ph.text)
                    )
                    for ph in document.preview_chunks
                ]  # fmt: skip
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

        await self._finish_rag(rag)
        logger.info("Finished indexing in RAG(id={}, status={})", rag.id, rag.status.value)

    async def on_cancel(self, request: IndexRequest):
        if (rag := self.state.get("rag")) is not None:
            rag = cast(Rag, rag)
            rag.mark_as_cancelled()
            await self._update_rag(rag)

    async def on_error(self, request: IndexRequest, error: Exception):
        if (rag := self.state.get("rag")) is not None:
            rag = cast(Rag, rag)
            rag.mark_as_failed(error)
            await self._update_rag(rag)

    async def _get_rag_under_uow(self, rag_id: int) -> Rag:
        rag = await self.uow.naive_rag_repo.get_rag(rag_id=rag_id)
        if rag is None:
            raise RagNotFoundError(rag_id=rag_id)
        self.state["rag"] = rag
        return rag

    async def _get_embedder_under_uow(self, rag_id: int) -> AbstractEmbedder:
        embedding_config = await self.uow.naive_rag_repo.get_embedding_config(rag_id=rag_id)
        if embedding_config is None:
            raise EmbeddingConfigNotFoundError(rag_id=rag_id)
        return build_embedder(embedding_config.provider, embedding_config)

    async def _get_documents_under_uow(self, rag_id: int, ids: frozenset[int]) -> list[Document]:
        documents = await self.uow.naive_rag_repo.get_documents(rag_id=rag_id, ids=ids)

        if not documents:
            raise DocumentNotFoundError(f"No Document found for RAG(id={rag_id}).")
        return documents

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
            has_completed_document = await self.uow.naive_rag_repo.has_completed_document(
                rag_id=rag.id
            )
            has_failed_document = await self.uow.naive_rag_repo.has_failed_document(rag_id=rag.id)

            if not has_completed_document:
                rag.mark_as_failed("Failed to indexing all documents.")
            elif has_failed_document:
                rag.mark_as_warning()
            else:
                rag.mark_as_completed()

            await self.uow.naive_rag_repo.update_rag(rag=rag)
            await self.uow.commit()
