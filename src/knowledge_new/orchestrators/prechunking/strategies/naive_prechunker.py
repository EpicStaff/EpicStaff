from enums import DocumentStatusEnum
from errors import DocumentNotFoundError, NoPreviewChunksProducedError
from loguru import logger
from models import Document, PrechunkRequest, PrechunkResponse
from orchestrators.prechunking.base import AbstractPrechunker
from services.chunkers import build_chunker
from services.file_text_extractors import build_file_text_extractor
from services.indexing_error_classifier import IndexingErrorClassifier


class NaivePrechunker(AbstractPrechunker):
    async def on_execute(self, request: PrechunkRequest) -> PrechunkResponse:
        document = await self._get_document(request.rag_id, request.document_id)
        self.state["document"] = document
        self.state["last_status"] = document.status

        if document.status == DocumentStatusEnum.CHUNKED and not document.is_required_reindex():
            logger.debug(
                "Reusing cached chunks for document {} in rag {}", document.id, request.rag_id
            )
            return PrechunkResponse(
                request=request, status=document.status, chunks=document.preview_chunks
            )

        extractor = build_file_text_extractor(document.extension)
        text = await extractor.extract(document.content)

        chunker = build_chunker(document.config.chunk_strategy, document.config)
        preview_chunks = await chunker.chunk(text)

        if not preview_chunks:
            raise NoPreviewChunksProducedError(document_id=document.id, rag_id=request.rag_id)

        document.preview_chunks = preview_chunks
        await self._update_document(request.rag_id, document)

        logger.info(
            "Prechunked document {} in rag {} into {} chunks",
            document.id,
            request.rag_id,
            len(preview_chunks),
        )
        return PrechunkResponse(
            request=request, status=document.status, chunks=document.preview_chunks
        )

    async def on_cancel(self, request: PrechunkRequest):
        if (document := self.state.get("document")) is not None:
            document: Document
            last_status = self.state["last_status"]
            if document.status not in (DocumentStatusEnum.CHUNKED, last_status):
                document.status = last_status
                await self._update_document(request.rag_id, document)

    async def on_error(self, request: PrechunkRequest, error: Exception):
        if (document := self.state.get("document")) is not None:
            document: Document
            error_code, error_message = IndexingErrorClassifier.classify(error)
            document.mark_failed(error_code, error_message)
            await self._update_document(request.rag_id, document)

    async def _get_document(self, rag_id: int, document_id: int) -> Document:
        async with self.uow:
            document = await self.uow.naive_rag_repo.get_document(
                rag_id=rag_id,
                document_id=document_id,
            )
        if document is None:
            raise DocumentNotFoundError(document_id=document_id, rag_id=rag_id)
        return document

    async def _update_document(self, rag_id: int, document: Document):
        async with self.uow:
            await self.uow.naive_rag_repo.update_document(rag_id=rag_id, document=document)
            await self.uow.naive_rag_repo.save_preview_chunks(
                document_id=document.id,
                chunks=document.preview_chunks,
            )
            await self.uow.commit()
