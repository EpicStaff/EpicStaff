from dataclasses import asdict

import pandas
from application.commands import RunIndex
from application.orchestrators.indexing.base import AbstractIndexOrchestrator
from domain.enums import DocumentStatusEnum, IndexStatusEnum
from domain.errors import DocumentNotFoundError, GraphRagConfigNotFoundError, RagNotFoundError
from domain.models import Rag
from graphrag.api import build_index
from graphrag_input import TextDocument
from loguru import logger


class GraphIndexOrchestrator(AbstractIndexOrchestrator):
    async def on_execute(self, command: RunIndex):
        async with self.uow:
            rag = await self._get_rag_under_uow(command.rag_id)
            config = await self._get_config_under_uow(rag.id)
            documents = await self._get_documents_under_uow(rag.id, command.document_ids)

        is_update_run = False
        if rag.status == IndexStatusEnum.COMPLETED:
            if self._has_indexed_document(documents):
                documents += await self._get_indexed_documents_excluding(
                    rag.id, command.document_ids
                )
            else:
                is_update_run = True

        rag.mark_as_processing(command.document_ids)
        await self._update_rag(rag)

        input_documents = pandas.DataFrame(data=[asdict(d) for d in documents])
        input_documents["human_readable_id"] = input_documents.index
        results = await build_index(
            config=config,
            input_documents=input_documents,
            verbose=True,
            is_update_run=is_update_run,
        )

        errors = {r.workflow: r.error for r in results if r.error is not None}
        if errors:
            await self._update_status_of_documents(
                rag.id, command.document_ids, status=DocumentStatusEnum.FAILED
            )
            raise ExceptionGroup(
                f"GraphRAG indexing failed for RAG(id={rag.id}) "
                f"in workflow(s): {', '.join(errors.keys())}.",
                list(errors.values()),
            )

        await self._update_status_of_documents(
            rag.id, command.document_ids, DocumentStatusEnum.COMPLETED
        )
        await self._finish_rag(rag, command.document_ids)

        logger.info("Finished indexing in RAG(id={}, status={}).", rag.id, rag.status.value)

    async def on_cancel(self, command: RunIndex):
        if (rag := self.state.get("rag")) is not None:
            rag: Rag
            rag.mark_as_cancelled()
            rag.finish_document(*command.document_ids)
            await self._update_rag(rag)

    async def on_error(self, command: RunIndex, error: Exception):
        if (rag := self.state.get("rag")) is not None:
            rag: Rag
            rag.mark_as_failed(error)
            rag.finish_document(*command.document_ids)
            await self._update_rag(rag)

    async def _get_rag_under_uow(self, rag_id: int) -> Rag:
        rag = await self.uow.graph_rag_repo.get_rag(rag_id=rag_id)
        if rag is None:
            raise RagNotFoundError(rag_id=rag_id)
        self.state["rag"] = rag
        return rag

    async def _get_config_under_uow(self, rag_id: int):
        config = await self.uow.graph_rag_repo.get_config(rag_id=rag_id)
        if not config:
            raise GraphRagConfigNotFoundError(rag_id=rag_id)
        return config

    async def _get_documents_under_uow(
        self, rag_id: int, ids: frozenset[int]
    ) -> list[TextDocument]:
        documents = await self.uow.graph_rag_repo.get_documents(rag_id=rag_id, ids=ids)

        if not documents:
            raise DocumentNotFoundError(f"No Document found for RAG(id={rag_id}).")
        return documents

    async def _get_indexed_documents_excluding(self, rag_id: int, ids: frozenset[int]):
        async with self.uow:
            return await self.uow.graph_rag_repo.get_indexed_documents_excluding(
                rag_id=rag_id, ids=ids
            )

    async def _update_rag(self, rag: Rag):
        async with self.uow:
            await self.uow.graph_rag_repo.update_rag(rag)
            await self.uow.commit()

    def _has_indexed_document(self, documents: list[TextDocument]) -> bool:
        return any(d.raw_data["status"] == DocumentStatusEnum.COMPLETED for d in documents)

    async def _update_status_of_documents(
        self,
        rag_id: int,
        ids: frozenset[int],
        status: DocumentStatusEnum,
    ):
        async with self.uow:
            await self.uow.graph_rag_repo.update_status_of_documents(
                rag_id=rag_id,
                ids=ids,
                status=status,
            )
            await self.uow.commit()

    async def _finish_rag(self, rag: Rag, document_ids: set[int]):
        async with self.uow:
            rag.finish_document(*document_ids)

            has_outdated = await self.uow.graph_rag_repo.has_outdated_document(rag_id=rag.id)
            has_completed = await self.uow.graph_rag_repo.has_completed_document(rag_id=rag.id)
            has_failed = await self.uow.graph_rag_repo.has_failed_document(rag_id=rag.id)

            if has_outdated:
                rag.mark_as_outdated()
            elif rag.indexing_document_ids:
                rag.status = IndexStatusEnum.PROCESSING
            elif has_completed:
                rag.mark_as_completed()
            elif has_failed:
                rag.mark_as_failed("Failed to index all documents.")
            else:
                rag.mark_as_new()
                # need to delete indexing result of graph rag

            if not has_outdated:
                rag.outdated_reasons.clear()

            await self.uow.graph_rag_repo.update_rag(rag=rag)
            await self.uow.commit()
