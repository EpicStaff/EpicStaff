from typing import Never

from application.orchestrators.indexing import build_indexer
from settings import settings
from domain.models import IndexRequest
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from presentation.handlers.base import AbstractCancellableHandler


class IndexHandler(AbstractCancellableHandler[IndexRequest, Never]):
    consumer_channel = settings.INDEX_REQUEST_CHANNEL
    request_class = IndexRequest

    async def handle(self, request: IndexRequest) -> None:
        uow = SQLAlchemyUnitOfWork()
        orchestrator = build_indexer(request.rag_strategy, uow)
        await orchestrator.execute(request)
        return None
