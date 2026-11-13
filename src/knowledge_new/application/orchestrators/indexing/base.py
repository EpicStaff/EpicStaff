import abc
from typing import Never

from application.commands import RunIndex
from application.orchestrators.base import AbstractOrchestrator
from application.ports import AbstractUnitOfWork
from foundation.cryptographer import AbstractCryptographer


class AbstractIndexOrchestrator(AbstractOrchestrator[RunIndex, Never], abc.ABC):
    """Abstract base for indexing a RAG's documents into searchable chunks."""

    def __init__(self, uow: AbstractUnitOfWork, cryptographer: AbstractCryptographer):
        super().__init__(uow)
        self.cryptographer = cryptographer
