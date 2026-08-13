import asyncio

from application import commands
from application.orchestrators.indexing import build_indexer
from application.orchestrators.prechunking import build_prechunker
from application.orchestrators.searching import build_search
from application.ports import AbstractUnitOfWork
from domain.enums import RAGStrategy
from litestar import Controller, post, status_codes
from presentation.rest import schemas

_background_tasks: set[asyncio.Task] = set()


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
    ) -> None:
        command = commands.RunIndex(
            rag_id=rag_id,
            document_ids=data.document_ids,
        )
        orchestrator = build_indexer(strategy, uow)
        task = asyncio.create_task(orchestrator.execute(command))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

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
    ) -> None:
        command = commands.RunPrechunk(rag_id=rag_id, **data.model_dump())
        orchestrator = build_prechunker(strategy, uow)
        await orchestrator.execute(command)
