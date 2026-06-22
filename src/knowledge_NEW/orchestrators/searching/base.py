"""Abstract base for RAG search strategies."""

import abc

from models import SearchRequest, SearchResponse
from database.unit_of_work import AbstractUnitOfWork

type TUoW = AbstractUnitOfWork


class AbstractSearch(abc.ABC):
    """Abstract base for searching a RAG for relevant chunks."""

    @abc.abstractmethod
    async def search(
        self, request: SearchRequest, uow: AbstractUnitOfWork
    ) -> SearchResponse:
        """Search the RAG named in `request` for chunks relevant to the query.

        Args:
            request: Search request with the RAG, query, and search config.
            uow: Unit of work providing repository access.

        Returns:
            The chunks matching the query.
        """
        pass
