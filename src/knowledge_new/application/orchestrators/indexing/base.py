import abc
from typing import Never

from application.orchestrators.base import AbstractOrchestrator
from domain.models import IndexRequest


class AbstractIndexer(AbstractOrchestrator[IndexRequest, Never], abc.ABC):
    """Abstract base for indexing a RAG's documents into searchable chunks."""
