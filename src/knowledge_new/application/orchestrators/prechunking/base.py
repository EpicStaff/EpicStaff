import abc
from typing import Never

from application.commands import RunPrechunk
from application.orchestrators.base import AbstractOrchestrator
from application.ports import AbstractDocumentContentReader, AbstractUnitOfWork


class AbstractPrechunkOrchestrator(AbstractOrchestrator[RunPrechunk, Never], abc.ABC):
    """Abstract base for producing preview chunks for a single document."""

    def __init__(self, uow: AbstractUnitOfWork, content_reader: AbstractDocumentContentReader):
        super().__init__(uow)
        self.content_reader = content_reader
