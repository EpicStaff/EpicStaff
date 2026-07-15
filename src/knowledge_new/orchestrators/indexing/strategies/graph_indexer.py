from dataclasses import asdict
from typing import cast

import pandas
from enums import IndexStatusEnum
from errors import DocumentNotFoundError, GraphRagConfigNotFoundError, RagNotFoundError
from graphrag.api import build_index
from loguru import logger
from models import IndexRequest, Rag
from orchestrators.indexing import AbstractIndexer


class GraphIndexer(AbstractIndexer):
    async def on_execute(self, request: IndexRequest):
        async with self.uow:
            rag = await self.uow.graph_rag_repo.get_rag(rag_id=request.rag_id)
            if not rag:
                raise RagNotFoundError(rag_id=request.rag_id)

            config = await self.uow.graph_rag_repo.get_config(rag_id=rag.id)
            if not config:
                raise GraphRagConfigNotFoundError(rag_id=rag.id)

            documents = await self.uow.graph_rag_repo.get_documents(
                rag_id=rag.id, ids=request.document_ids
            )
            if not documents:
                raise DocumentNotFoundError(f"No Documents found for RAG(id={rag.id}).")

        rag.mark_as_processing(request.document_ids)
        async with self.uow:
            await self.uow.graph_rag_repo.update_rag(rag)
            await self.uow.commit()

        results = await build_index(
            config=config,
            input_documents=pandas.DataFrame(data=[asdict(d) for d in documents]),
            verbose=True,
        )

        errors = {r.workflow: r.error for r in results if r.error is not None}
        if errors:
            raise ExceptionGroup(
                f"GraphRAG indexing failed for RAG(id={rag.id}) "
                f"in workflow(s): {', '.join(errors.keys())}.",
                list(errors.values()),
            )

        rag.status = IndexStatusEnum.COMPLETED
        rag.indexing_document_ids.clear()
        async with self.uow:
            await self.uow.graph_rag_repo.update_rag(rag)
            await self.uow.commit()

        logger.success("RAG(id={}) indexed successfully.", rag.id)

    async def on_cancel(self, request: IndexRequest):
        if (rag := self.state.get("rag")) is not None:
            rag = cast(Rag, rag)
            rag.mark_as_cancelled()
            async with self.uow:
                await self.uow.graph_rag_repo.update_rag(rag)
                await self.uow.commit()

    async def on_error(self, request: IndexRequest, error: Exception):
        if (rag := self.state.get("rag")) is not None:
            rag = cast(Rag, rag)
            rag.mark_as_failed(error)
            async with self.uow:
                await self.uow.graph_rag_repo.update_rag(rag)
                await self.uow.commit()
