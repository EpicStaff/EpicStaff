import asyncio
from typing import Literal

from application import commands
from application.orchestrators.indexing import build_indexer
from application.orchestrators.prechunking import build_prechunker
from application.orchestrators.searching import build_search
from application.ports import AbstractUnitOfWork
from common.utils import make_key
from domain.enums import RAGStrategy
from litestar import Controller, post, status_codes, get, delete

from domain.errors import NotRunningOperationError
from infrastructure.task_register import TaskRegister
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
        task_register: TaskRegister,
    ) -> None:
        command = commands.RunIndex(
            rag_id=rag_id,
            document_ids=data.document_ids,
        )
        orchestrator = build_indexer(strategy, uow)
        task = asyncio.create_task(orchestrator.execute(command))
        key = make_key('rag', strategy, rag_id, 'index')
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
        task_register: TaskRegister,
    ) -> None:
        command = commands.RunPrechunk(
            rag_id=rag_id,
            document_id=data.document_id,
            chunking_config=data.chunking_config,
        )
        orchestrator = build_prechunker(strategy, uow)
        task = asyncio.create_task(orchestrator.execute(command))
        key = make_key('rag', strategy, rag_id, 'prechunk')
        task_register.register(key, task)

    @delete(
        path="{rag_id:int}/{operation:str}/cancel/",
        summary="Cancel a running index or prechunk",
    )
    async def cancel_operation(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        operation: Literal['index', 'prechunk'],
        task_register: TaskRegister,
    ) -> None:
        key = make_key('rag', strategy, rag_id, operation)
        if not task_register.cancel(key):
            raise NotRunningOperationError(operation=operation, rag_id=rag_id)
