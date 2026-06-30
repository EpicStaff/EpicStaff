from errors import (
    EmbeddingConfigNotFoundError,
    DocumentNotFoundError,
    NoPreviewChunksProducedError,
    ChunksNotIndexedError,
    RepositoryError,
)
from enums import IndexStatusEnum, DocumentStatusEnum
from models import IndexRequest, IndexedChunk, Document
from orchestrators.indexing import AbstractIndexer
from services.chunkers import build_chunker
from services.embedders import build_embedder, AbstractEmbedder
from services.file_text_extractors import build_file_text_extractor
from services.indexing_error_classifier import IndexingErrorClassifier


class NaiveIndexer(AbstractIndexer):
    async def on_execute(self, request: IndexRequest) -> None:
        async with self.uow:
            embedder = await self._get_embedder_under_uow(request.rag_id)
            documents = await self._get_documents_under_uow(request.rag_id)

        await self._update_rag_status(request.rag_id, IndexStatusEnum.PROCESSING)

        has_completed_document = False
        has_failed_document = False
        for document in documents:
            if (
                document.status == DocumentStatusEnum.COMPLETED
                and not document.is_required_reindex()
            ):
                has_completed_document = True
                continue

            try:
                if not document.preview_chunks or document.is_required_reindex():
                    document.status = DocumentStatusEnum.CHUNKING
                    await self._update_document(request.rag_id, document)

                    extractor = build_file_text_extractor(document.extension)
                    text = await extractor.extract(document.content)

                    chuncker = build_chunker(
                        document.config.chunk_strategy, document.config
                    )
                    preview_chunks = await chuncker.chunk(text)
                    if not preview_chunks:
                        raise NoPreviewChunksProducedError(
                            document_id=document.id,
                            rag_id=request.rag_id,
                        )
                    document.preview_chunks = preview_chunks

                    document.status = DocumentStatusEnum.CHUNKED
                    await self._update_document(request.rag_id, document)

                document.status = DocumentStatusEnum.INDEXING
                await self._update_document(request.rag_id, document)
                # TODO: embed batch of chunks instead of one per time.
                indexed_chunks = [
                    IndexedChunk(
                        **ph.model_dump(),
                        vector=await embedder.embed(ph.text),
                    )
                    for ph in document.preview_chunks
                ]
                if not indexed_chunks:
                    raise ChunksNotIndexedError(
                        document_id=document.id,
                        rag_id=request.rag_id,
                    )
                document.indexed_chunks = indexed_chunks

            except RepositoryError:
                raise

            except Exception as e:
                error_code, error_message = IndexingErrorClassifier.classify(e)
                document.mark_failed(error_code, error_message)
                has_failed_document = True

            else:
                document.mark_completed()
                has_completed_document = True

            await self._update_document(request.rag_id, document)

        if not has_completed_document:
            indexing_status = IndexStatusEnum.FAILED
        elif has_failed_document:
            indexing_status = IndexStatusEnum.WARNING
        else:
            indexing_status = IndexStatusEnum.COMPLETED
        await self._update_rag_status(request.rag_id, indexing_status)

    async def on_cancel(self, request: IndexRequest):
        await self._update_rag_status(request.rag_id, IndexStatusEnum.CANCELLED)

    async def on_error(self, request: IndexRequest, exc: Exception):
        # TODO: update rag errors
        await self._update_rag_status(request.rag_id, IndexStatusEnum.FAILED)

    async def _get_embedder_under_uow(self, rag_id: int) -> AbstractEmbedder:
        embedding_config = await self.uow.naive_rag_repo.get_embedding_config(
            rag_id=rag_id
        )
        if embedding_config is None:
            raise EmbeddingConfigNotFoundError(rag_id=rag_id)
        return build_embedder(embedding_config.provider, embedding_config)

    async def _get_documents_under_uow(self, rag_id: int) -> list[Document]:
        documents = await self.uow.naive_rag_repo.get_all_documents(rag_id=rag_id)

        if not documents:
            raise DocumentNotFoundError(f"No Document found for RAG(id={rag_id}).")
        return documents

    async def _update_rag_status(self, rag_id: int, status: IndexStatusEnum):
        async with self.uow:
            await self.uow.naive_rag_repo.update_rag_status(
                rag_id=rag_id,
                status=status,
            )
            await self.uow.commit()

    async def _update_document(self, rag_id: int, document: Document):
        async with self.uow:
            await self.uow.naive_rag_repo.update_document(
                rag_id=rag_id,
                document=document,
            )
            if document.status == DocumentStatusEnum.COMPLETED:
                await self.uow.naive_rag_repo.save_indexed_chunks(
                    document_id=document.id,
                    chunks=document.indexed_chunks,
                )
            await self.uow.commit()
