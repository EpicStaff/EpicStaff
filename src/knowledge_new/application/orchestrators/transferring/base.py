import abc

from application.commands import (
    ExportGraphArtifacts,
    RestoreGraphArtifacts,
    RewriteGraphDocumentIds,
)
from application.orchestrators.base import AbstractOrchestrator
from application.ports.artifact_store import AbstractArtifactStore
from application.ports.unit_of_work import AbstractUnitOfWork
from application.results import ArtifactExportResult


class ArtifactStoreOrchestratorMixin:
    """Give an orchestrator the artifact store next to the unit of work."""

    def __init__(self, uow: AbstractUnitOfWork, artifact_store: AbstractArtifactStore):
        super().__init__(uow)
        self.artifact_store = artifact_store


class AbstractArtifactExportOrchestrator(
    ArtifactStoreOrchestratorMixin,
    AbstractOrchestrator[ExportGraphArtifacts, ArtifactExportResult],
    abc.ABC,
):
    """Check that a RAG's index can be exported and return it as a tar stream."""


class AbstractArtifactRestoreOrchestrator(
    ArtifactStoreOrchestratorMixin,
    AbstractOrchestrator[RestoreGraphArtifacts, None],
    abc.ABC,
):
    """Write an exported index tar into a RAG's storage."""


class AbstractDocumentIdRewriteOrchestrator(
    ArtifactStoreOrchestratorMixin,
    AbstractOrchestrator[RewriteGraphDocumentIds, None],
    abc.ABC,
):
    """Replace the document ids inside a restored index with the importing side's ids."""
