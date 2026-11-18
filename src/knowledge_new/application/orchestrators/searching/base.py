import abc

from application.commands import RunSearch
from application.orchestrators.base import AbstractOrchestrator
from application.ports import AbstractUnitOfWork
from application.results import SearchResult
from foundation.cryptographer import AbstractCryptographer


class AbstractSearchOrchestrator(AbstractOrchestrator[RunSearch, SearchResult], abc.ABC):
    """Search the RAG named in `request` for chunks relevant to the query."""

    def __init__(self, uow: AbstractUnitOfWork, cryptographer: AbstractCryptographer):
        super().__init__(uow)
        self.cryptographer = cryptographer
