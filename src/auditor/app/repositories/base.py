from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from src.shared.models import BaseAuditEvent

T = TypeVar("T", bound=BaseAuditEvent)


class AuditRepository(ABC, Generic[T]):  # noqa: UP046 - T is imported by implementations
    """
    Base interface for audit-event storage backends, generic over the event
    model (bounded to BaseAuditEvent - see src/shared/models/audit/base.py).
    Every domain shares this one interface and the OpenSearchAuditRepository
    implementation; a domain supplies its own event model, IndexSpec, and
    FieldCatalog rather than getting its own repository class.

    All storage-specific repositories (OpenSearchAuditRepository, etc.)
    inherit from this base class and implement the actual read/write
    mechanics for their backend.
    """

    @abstractmethod
    async def write_batch(self, events: list[T]) -> list[dict] | None:
        """
        Persist a batch of audit events. Returns the per-document error
        entries for any event that failed to persist, or None if all did.

        Must be idempotent: re-sending a batch that includes an event with
        an `id` already stored must overwrite that event in place, not
        create a duplicate.
        """

    @abstractmethod
    async def query(
        self,
        query: dict[str, Any],
        cursor: str | None = None,
        size: int = 50,
    ) -> tuple[list[T], str | None]:
        """
        Query audit events using a fully-compiled, backend-native
        query clause (see repositories/compiler.py) - the
        output of compiling a FilterNode AST plus the always-injected
        org_id/retention_days clauses.

        Paginated by cursor/size: returns (events for this page, next
        cursor or None if there are no more pages).
        """

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying connection/client resources on shutdown."""
