import asyncio
from typing import Literal

from application import commands
from application.commands import GetMetrics, RemoveRag
from application.orchestrators.indexing import build_indexer
from application.orchestrators.metrics import build_metrics
from application.orchestrators.prechunking import build_prechunker
from application.orchestrators.removing.factory import build_remover
from application.orchestrators.searching import build_search
from application.ports import AbstractUnitOfWork
from application.ports.task_register import AbstractTaskRegister
from common.utils import make_key
from domain.enums import RAGStrategy
from domain.errors import NotRunningOperationError
from litestar import Controller, delete, get, post, status_codes
from presentation.rest import schemas


class RagController(Controller):
    path = "rags/{strategy:str}/"
    tags = ("RAG",)

    @post(
        path="{rag_id:int}/index/",
        status_code=status_codes.HTTP_202_ACCEPTED,
        summary="Index documents",
    )
    async def index(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        data: schemas.IndexInputSchema,
        uow: AbstractUnitOfWork,
        task_register: AbstractTaskRegister,
    ) -> None:
        command = commands.RunIndex(
            rag_id=rag_id,
            document_ids=data.document_ids,
            embedding_api_key=data.embedding_api_key,
            llm_api_key=data.llm_api_key,
        )
        orchestrator = build_indexer(strategy, uow)
        task = asyncio.create_task(orchestrator.execute(command))
        key = make_key("rag", strategy, rag_id, "index")
        task_register.register(key, task)

    @post(
        path="{rag_id:int}/search/",
        status_code=status_codes.HTTP_200_OK,
        summary="Search the collection",
    )
    async def search(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        data: schemas.SearchInputSchema,
        uow: AbstractUnitOfWork,
    ) -> schemas.SearchOutputSchema:
        command = commands.RunSearch(
            rag_id=rag_id,
            query=data.query,
            search_config=data.search_config,
            embedding_api_key=data.embedding_api_key,
            llm_api_key=data.llm_api_key,
        )
        orchestrator = build_search(strategy, uow)
        result = await orchestrator.execute(command)
        return schemas.SearchOutputSchema.model_validate(result)

    @post(
        path="{rag_id:int}/prechunk/",
        status_code=status_codes.HTTP_202_ACCEPTED,
        summary="Preview chunking",
    )
    async def prechunk(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        data: schemas.PrechunkInputSchema,
        uow: AbstractUnitOfWork,
    ) -> schemas.PrechunkOutputSchema:
        command = commands.RunPrechunk(
            rag_id=rag_id,
            document_id=data.document_id,
            chunking_config=data.chunking_config,
        )
        orchestrator = build_prechunker(strategy, uow)
        result = await orchestrator.execute(command)
        return schemas.PrechunkOutputSchema.model_validate(result)

    @get(
        path="{rag_id:int}/metrics/",
        status_code=status_codes.HTTP_200_OK,
        summary="Corpus chunk metrics",
    )
    async def metrics(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        uow: AbstractUnitOfWork,
    ) -> schemas.MetricsOutputSchema:
        orchestrator = build_metrics(strategy, uow)
        result = await orchestrator.execute(GetMetrics(rag_id=rag_id))
        return schemas.MetricsOutputSchema.model_validate(result)

    @delete(
        path="{rag_id:int}/cancel/{operation:str}/",
        summary="Cancel a running index",
    )
    async def cancel_operation(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        operation: Literal["index"],
        task_register: AbstractTaskRegister,
    ) -> None:
        key = make_key("rag", strategy, rag_id, operation)
        if not task_register.cancel(key):
            raise NotRunningOperationError(operation=operation, rag_id=rag_id)

    @delete(path="{rag_id:int}/", summary="Delete a RAG and its result storage.")
    async def remove(
        self, strategy: RAGStrategy, rag_id: int, uow: AbstractUnitOfWork
    ) -> None:
        command = RemoveRag(rag_id=rag_id)
        orchestrator = build_remover(strategy, uow)
        await orchestrator.execute(command)
