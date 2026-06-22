"""Abstract base for document indexing strategies."""

import abc

from models import IndexRequest
from database.unit_of_work import AbstractUnitOfWork


class AbstractIndexer(abc.ABC):
    """Abstract base for indexing a RAG's documents into searchable chunks."""

    @abc.abstractmethod
    async def index(self, request: IndexRequest, uow: AbstractUnitOfWork):
        """Index the documents of the RAG named in `request`.

        Args:
            request: Indexing request identifying the RAG to index.
            uow: Unit of work providing repository access.
        """
        pass
