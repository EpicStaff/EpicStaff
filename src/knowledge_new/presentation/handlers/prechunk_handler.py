from application.orchestrators.prechunking import build_prechunker
from settings import settings
from domain.models import PrechunkRequest, PrechunkResponse
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from presentation.handlers.base import AbstractCancellableHandler


class PrechunkHandler(AbstractCancellableHandler[PrechunkRequest, PrechunkResponse]):
    consumer_channel = settings.PRECHUNK_REQUEST_CHANNEL
    producer_channel = settings.PRECHUNK_RESPONSE_CHANNEL
    request_class = PrechunkRequest
    response_class = PrechunkResponse

    async def handle(self, request: PrechunkRequest) -> PrechunkResponse:
        uow = SQLAlchemyUnitOfWork()
        orchestrator = build_prechunker(request.rag_strategy, uow)
        return await orchestrator.execute(request)
