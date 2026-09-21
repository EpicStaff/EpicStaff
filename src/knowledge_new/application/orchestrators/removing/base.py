import abc

from application.orchestrators.base import AbstractOrchestrator


class AbstractRagRemoveOrchestrator(AbstractOrchestrator, abc.ABC):
    """Abstract base for orchestrators that delete a RAG."""
