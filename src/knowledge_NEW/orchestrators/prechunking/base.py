"""Abstract base for document prechunking strategies."""

import abc

from models import PrechunkRequest, PrechunkResponse
from database.unit_of_work import AbstractUnitOfWork


class AbstractPrechunker(abc.ABC):
    """Abstract base for producing preview chunks for a single document."""

    @abc.abstractmethod
    async def chunk(
        self, request: PrechunkRequest, uow: AbstractUnitOfWork
    ) -> PrechunkResponse:
        """Produce preview chunks for the document named in `request`.

        Args:
            request: Prechunk request identifying the RAG and document.
            uow: Unit of work providing repository access.

        Returns:
            The preview chunks produced for the document.
        """
        pass
