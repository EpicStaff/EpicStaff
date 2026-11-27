from application.orchestrators.prechunking import strategies
from application.orchestrators.prechunking.base import AbstractPrechunkOrchestrator
from application.ports import AbstractDocumentContentReader, AbstractUnitOfWork
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

_STRATEGIES: dict[RAGStrategy, type[AbstractPrechunkOrchestrator]] = {
    RAGStrategy.NAIVE: strategies.NaivePrechunkOrchestrator,
}


def build_prechunker(
    strategy: RAGStrategy, uow: AbstractUnitOfWork, content_reader: AbstractDocumentContentReader
) -> AbstractPrechunkOrchestrator:
    """Build the prechunker registered for `strategy`.

    Args:
        strategy: RAG strategy to build a prechunker for.
        uow: Unit of work providing repository access.
        content_reader: Reads the document's stored file.

    Raises:
        UnsupportedError: If no prechunker is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("index strategy", strategy)
    return _STRATEGIES[strategy](uow, content_reader)
