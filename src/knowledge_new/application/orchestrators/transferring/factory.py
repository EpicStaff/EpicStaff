from typing import TYPE_CHECKING

from application.orchestrators.transferring.base import (
    AbstractArtifactExportOrchestrator,
    AbstractArtifactRestoreOrchestrator,
    AbstractDocumentIdRewriteOrchestrator,
)
from application.ports import AbstractUnitOfWork
from application.ports.artifact_store import AbstractArtifactStore
from common.lazy_import import LazyImport
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

if TYPE_CHECKING:
    from application.orchestrators.transferring.strategies.graph_artifacts import (
        GraphArtifactExportOrchestrator,
        GraphArtifactRestoreOrchestrator,
        GraphDocumentIdRewriteOrchestrator,
    )
else:
    _GRAPH_ARTIFACTS = "application.orchestrators.transferring.strategies.graph_artifacts"
    GraphArtifactExportOrchestrator = LazyImport(
        _GRAPH_ARTIFACTS, obj="GraphArtifactExportOrchestrator"
    )
    GraphArtifactRestoreOrchestrator = LazyImport(
        _GRAPH_ARTIFACTS, obj="GraphArtifactRestoreOrchestrator"
    )
    GraphDocumentIdRewriteOrchestrator = LazyImport(
        _GRAPH_ARTIFACTS, obj="GraphDocumentIdRewriteOrchestrator"
    )

# Naive RAG keeps its whole index in Postgres, so Django exports it without this service.
_EXPORTERS: dict[RAGStrategy, type[AbstractArtifactExportOrchestrator]] = {
    RAGStrategy.GRAPH: GraphArtifactExportOrchestrator,
}
_RESTORERS: dict[RAGStrategy, type[AbstractArtifactRestoreOrchestrator]] = {
    RAGStrategy.GRAPH: GraphArtifactRestoreOrchestrator,
}
_REWRITERS: dict[RAGStrategy, type[AbstractDocumentIdRewriteOrchestrator]] = {
    RAGStrategy.GRAPH: GraphDocumentIdRewriteOrchestrator,
}


def build_artifact_exporter(
    strategy: RAGStrategy, uow: AbstractUnitOfWork, artifact_store: AbstractArtifactStore
) -> AbstractArtifactExportOrchestrator:
    """Build the index exporter registered for `strategy`.

    Raises:
        UnsupportedError: If no exporter is registered for `strategy`.
    """
    if strategy not in _EXPORTERS:
        raise UnsupportedError(that="artifact export strategy", got=strategy)
    return _EXPORTERS[strategy](uow, artifact_store)


def build_artifact_restorer(
    strategy: RAGStrategy, uow: AbstractUnitOfWork, artifact_store: AbstractArtifactStore
) -> AbstractArtifactRestoreOrchestrator:
    """Build the index restorer registered for `strategy`.

    Raises:
        UnsupportedError: If no restorer is registered for `strategy`.
    """
    if strategy not in _RESTORERS:
        raise UnsupportedError(that="artifact restore strategy", got=strategy)
    return _RESTORERS[strategy](uow, artifact_store)


def build_document_id_rewriter(
    strategy: RAGStrategy, uow: AbstractUnitOfWork, artifact_store: AbstractArtifactStore
) -> AbstractDocumentIdRewriteOrchestrator:
    """Build the document id rewriter registered for `strategy`.

    Raises:
        UnsupportedError: If no rewriter is registered for `strategy`.
    """
    if strategy not in _REWRITERS:
        raise UnsupportedError(that="document id rewrite strategy", got=strategy)
    return _REWRITERS[strategy](uow, artifact_store)
