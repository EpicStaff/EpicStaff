import abc
from typing import Never

from application.commands import RunIndex
from application.orchestrators.base import AbstractOrchestrator


class AbstractIndexOrchestrator(AbstractOrchestrator[RunIndex, Never], abc.ABC):
    """Abstract base for indexing a RAG's documents into searchable chunks."""
