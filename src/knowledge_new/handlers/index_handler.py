from typing import Never

from database.unit_of_work import SQLAlchemyUnitOfWork
from handlers.base import AbstractCancellableHandler
from models import IndexRequest
from orchestrators.indexing import build_indexer
from settings import settings


class IndexHandler(AbstractCancellableHandler[IndexRequest, Never]):
    consumer_channel = settings.INDEX_REQUEST_CHANNEL
    request_class = IndexRequest

    async def handle(self, request: IndexRequest) -> None:
        uow = SQLAlchemyUnitOfWork()
        orchestrator = build_indexer(request.rag_strategy, uow)
        await orchestrator.execute(request)
        return None
