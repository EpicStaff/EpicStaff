import abc

from application.commands import RunSearch
from application.orchestrators.base import AbstractOrchestrator
from application.results import SearchResult


class AbstractSearchOrchestrator(AbstractOrchestrator[RunSearch, SearchResult], abc.ABC):
    """Search the RAG named in `request` for chunks relevant to the query."""
