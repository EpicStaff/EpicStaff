from collections.abc import Callable
from types import ModuleType

from app.db.opensearch_client import build_opensearch_client
from app.domains.base import IndexSpec
from app.repositories.base import AuditRepository
from app.repositories.opensearch_repository import OpenSearchAuditRepository
from pydantic import BaseModel


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
    """Builds the repository for the configured AUDIT_STORAGE_BACKEND over one domain's index."""
    builder = _BACKEND_BUILDERS.get(settings.AUDIT_STORAGE_BACKEND)

    if builder is None:
        raise ValueError(f"Unsupported audit storage backend: {settings.AUDIT_STORAGE_BACKEND!r}")

    return builder(settings, index=index, model=model)
