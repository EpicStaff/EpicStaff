from typing import Callable

from app.core.settings import Settings
from app.db.opensearch_client import build_opensearch_client
from app.repositories.base import SessionAuditRepository
from app.repositories.opensearch_repository import OpenSearchSessionAuditRepository


def _build_opensearch_session_audit_repository(settings: Settings) -> SessionAuditRepository:
    client = build_opensearch_client(settings)
    return OpenSearchSessionAuditRepository(client)


_BACKEND_BUILDERS: dict[str, Callable[[Settings], SessionAuditRepository]] = {
    "opensearch": _build_opensearch_session_audit_repository,
}


def build_session_audit_repository(settings: Settings) -> SessionAuditRepository:
    """
    Construct the SessionAuditRepository for the configured storage backend.

    Scoped specifically to the session-audit domain, same as
    repositories/base.py. A future domain (e.g. user actions) gets its own
    sibling factory - not a second dict-of-builders added to this file.

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
            f"Unsupported session-audit storage backend: {settings.AUDIT_STORAGE_BACKEND!r}"
        )

    return builder(settings)
