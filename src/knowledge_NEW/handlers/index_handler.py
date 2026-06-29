from typing import Never

from loguru import logger

from database.unit_of_work import SQLAlchemyUnitOfWork
from handlers import AbstractHandler
from models import IndexRequest
from orchestrators.indexing import build_indexer
from settings import settings


class IndexHandler(AbstractHandler[IndexRequest, Never]):
    consumer_channel = settings.INDEX_REQUEST_CHANNEL
    request_class = IndexRequest

    async def handle(self, request: IndexRequest) -> None:
        logger.info("Handling index by request: {}", request)
        uow = SQLAlchemyUnitOfWork()
        orchestrator = build_indexer(request.rag_strategy, uow)
        await orchestrator.execute(request)
        return None
