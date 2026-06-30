import abc
from typing import Never

from models import IndexRequest
from orchestrators.base import AbstractOrchestrator


class AbstractIndexer(AbstractOrchestrator[IndexRequest, Never], abc.ABC):
    """Abstract base for indexing a RAG's documents into searchable chunks."""
