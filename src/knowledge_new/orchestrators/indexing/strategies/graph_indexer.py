from dataclasses import asdict
from typing import Literal

import pandas

from enums import IndexStatusEnum
from errors import DocumentNotFoundError, GraphRagConfigNotFoundError, RagNotFoundError
from graphrag.api import build_index
from graphrag_input import TextDocument
from loguru import logger
from models import IndexRequest, Rag
from orchestrators.indexing import AbstractIndexer


class GraphIndexer(AbstractIndexer):
    async def on_execute(self, request: IndexRequest):
        async with self.uow:
            rag = await self._get_rag_under_uow(request.rag_id)
            config = await self._get_config_under_uow(rag.id)
            documents = await self._get_documents_under_uow(rag.id, request.document_ids)

        is_update_run = False
        if rag.status == IndexStatusEnum.COMPLETED:
            if self._has_indexed_document(documents):
                documents += await self._get_indexed_documents_excluding(
                    rag.id, request.document_ids
                )
            else:
                is_update_run = True


        rag.mark_as_processing(request.document_ids)
        await self._update_rag(rag)

        results = await build_index(
            config=config,
            input_documents=pandas.DataFrame(data=[asdict(d) for d in documents]),
            verbose=True,
            is_update_run=is_update_run,
        )

        errors = {r.workflow: r.error for r in results if r.error is not None}
        if errors:
            raise ExceptionGroup(
                f"GraphRAG indexing failed for RAG(id={rag.id}) "
                f"in workflow(s): {', '.join(errors.keys())}.",
                list(errors.values()),
            )

        await self._update_status_of_documents(rag.id, request.document_ids, status='completed')
        rag.mark_as_completed()
        await self._update_rag(rag)

        logger.info("Finished indexing in RAG(id={}, status={}).", rag.id, rag.status.value)

    async def on_cancel(self, request: IndexRequest):
        if (rag := self.state.get("rag")) is not None:
            rag: Rag
            rag.mark_as_cancelled()
            await self._update_rag(rag)

    async def on_error(self, request: IndexRequest, error: Exception):
        if (rag := self.state.get("rag")) is not None:
            rag: Rag
            rag.mark_as_failed(error)
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
        return any(d.raw_data['status'] == 'completed' for d in documents)

    async def _update_status_of_documents(
        self,
        rag_id: int,
        ids: frozenset[int],
        status: Literal['new', 'completed'],
    ):
        async with self.uow:
            await self.uow.graph_rag_repo.update_status_of_documents(
                rag_id=rag_id,
                ids=ids,
                status=status,
            )
            await self.uow.commit()