import abc

from application.orchestrators.base import AbstractOrchestrator
from domain.models import SearchRequest, SearchResponse


class AbstractSearch(AbstractOrchestrator[SearchRequest, SearchResponse], abc.ABC):
    """Search the RAG named in `request` for chunks relevant to the query."""
