import abc

from models import SearchRequest, SearchResponse
from orchestrators.base import AbstractOrchestrator


class AbstractSearch(AbstractOrchestrator[SearchRequest, SearchResponse], abc.ABC):
    """Search the RAG named in `request` for chunks relevant to the query."""
