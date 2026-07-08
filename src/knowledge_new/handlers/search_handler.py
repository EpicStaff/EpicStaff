from database.unit_of_work import SQLAlchemyUnitOfWork
from handlers.base import AbstractCancellableHandler
from models import SearchRequest, SearchResponse
from orchestrators.searching import build_search
from settings import settings


class SearchHandler(AbstractCancellableHandler[SearchRequest, SearchResponse]):
    consumer_channel = settings.SEARCH_REQUEST_CHANNEL
    producer_channel = settings.SEARCH_RESPONSE_CHANNEL
    request_class = SearchRequest
    response_class = SearchResponse

    async def handle(self, request: SearchRequest) -> SearchResponse:
        uow = SQLAlchemyUnitOfWork()
        orchestrator = build_search(request.search_config.rag_strategy, uow)
        return await orchestrator.execute(request)
