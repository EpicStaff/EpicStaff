from database.unit_of_work import SQLAlchemyUnitOfWork
from models import (
    CancelRequest,
    IndexRequest,
    PrechunkRequest,
    PrechunkResponse,
    Rag,
    SearchRequest,
    SearchResponse,
)
from enums import RAGStrategy
from orchestrators.indexing import build_indexer
from orchestrators.prechunking import build_prechunker
from orchestrators.searching import build_search
from services.task_register import task_register
from utils import hash_dict


async def index(request: IndexRequest) -> None:
    uow = SQLAlchemyUnitOfWork()
    await build_indexer(request.rag_strategy, uow).execute(request)


async def prechunk(request: PrechunkRequest) -> PrechunkResponse:
    uow = SQLAlchemyUnitOfWork()
    return await build_prechunker(request.rag_strategy, uow).execute(request)


async def search(request: SearchRequest) -> SearchResponse:
    uow = SQLAlchemyUnitOfWork()
    return await build_search(request.search_config.rag_strategy, uow).execute(request)


def cancel(request: CancelRequest) -> bool:
    return task_register.cancel(hash_dict(request.target_request))


async def index_status(rag_id: int, strategy: RAGStrategy) -> Rag | None:
    uow = SQLAlchemyUnitOfWork()
    async with uow:
        repo = (
            uow.naive_rag_repo if strategy == RAGStrategy.NAIVE else uow.graph_rag_repo
        )
        return await repo.get_rag(rag_id)
