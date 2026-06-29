from loguru import logger

from database.unit_of_work import SQLAlchemyUnitOfWork
from handlers.base import AbstractCancellableHandler
from models import PrechunkRequest, PrechunkResponse
from orchestrators.prechunking import build_prechunker
from settings import settings


class PrechunkHandler(AbstractCancellableHandler[PrechunkRequest, PrechunkResponse]):
    consumer_channel = settings.PRECHUNK_REQUEST_CHANNEL
    producer_channel = settings.PRECHUNK_RESPONSE_CHANNEL
    request_class = PrechunkRequest
    response_class = PrechunkResponse

    async def handle(self, request: PrechunkRequest) -> PrechunkResponse:
        logger.info("Handling prechunk by request: {}", request)
        uow = SQLAlchemyUnitOfWork()
        orchestrator = build_prechunker(request.rag_strategy, uow)
        return await orchestrator.execute(request)
