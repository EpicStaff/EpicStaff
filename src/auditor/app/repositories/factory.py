from types import ModuleType
from typing import Callable

from pydantic import BaseModel

from app.db.opensearch_client import build_opensearch_client
from app.domains.base import IndexSpec
from app.repositories.base import AuditRepository
from app.repositories.opensearch_repository import OpenSearchAuditRepository


def _build_opensearch_audit_repository(
    settings: ModuleType, *, index: IndexSpec, model: type[BaseModel]
) -> AuditRepository:
    client = build_opensearch_client(settings)
    return OpenSearchAuditRepository(client, index, model)


_BACKEND_BUILDERS: dict[str, Callable[..., AuditRepository]] = {
    "opensearch": _build_opensearch_audit_repository,
}


def build_audit_repository(
    settings: ModuleType, *, index: IndexSpec, model: type[BaseModel]
) -> AuditRepository:
    """
    Construct the AuditRepository for the configured storage backend.

    Shared across every domain - a domain supplies its own IndexSpec/event
    model (see app/domains/base.py::AuditDomain), not a second
    dict-of-builders added to this file.

    Only "opensearch" is wired up today, but this project has already
    swapped storage backends once during design (ClickHouse -> OpenSearch)
    before a line of repository code existed, so this is a real
    dict-of-builders selector (mirroring RAGStrategyFactory's dict-of-classes
    pattern in knowledge/rag/rag_strategy_factory.py) from day one rather
    than a single hardcoded call.

    Repositories don't share a uniform constructor (a future Mongo backend
    would need a completely different client type), so this maps to builder
    functions rather than bare classes.
    """
    builder = _BACKEND_BUILDERS.get(settings.AUDIT_STORAGE_BACKEND)

    if builder is None:
        raise ValueError(
            f"Unsupported audit storage backend: {settings.AUDIT_STORAGE_BACKEND!r}"
        )

    return builder(settings, index=index, model=model)
