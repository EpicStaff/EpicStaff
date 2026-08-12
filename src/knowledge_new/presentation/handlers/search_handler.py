from application.orchestrators.searching import build_search
from settings import settings
from domain.models import SearchRequest, SearchResponse
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from presentation.handlers.base import AbstractCancellableHandler


class SearchHandler(AbstractCancellableHandler[SearchRequest, SearchResponse]):
    consumer_channel = settings.SEARCH_REQUEST_CHANNEL
    producer_channel = settings.SEARCH_RESPONSE_CHANNEL
    request_class = SearchRequest
    response_class = SearchResponse

    async def handle(self, request: SearchRequest) -> SearchResponse:
        uow = SQLAlchemyUnitOfWork()
        orchestrator = build_search(request.search_config.rag_strategy, uow)
        return await orchestrator.execute(request)
