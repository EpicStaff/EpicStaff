from abc import ABC, abstractmethod
from typing import Any

from src.shared.models import SessionAuditEvent


class SessionAuditRepository(ABC):
    """
    Base interface for session-audit event storage backends.

    Scoped specifically to the session-audit domain (SessionAuditEvent) -
    a future domain (e.g. user actions) gets its own sibling repository
    interface + implementations, not a method added to this one.

    All storage-specific repositories (OpenSearchSessionAuditRepository,
    etc.) inherit from this base class and implement the actual read/write
    mechanics for their backend.
    """

    @abstractmethod
    async def write_batch(self, events: list[SessionAuditEvent]) -> None:
        """
        Persist a batch of session-audit events.

        Must be idempotent: re-sending a batch that includes an event with
        an `id` already stored must overwrite that event in place, not
        create a duplicate.

        Args:
            events: The session-audit events to persist.
        """
        pass

    @abstractmethod
    async def query(
        self,
        filters: dict[str, Any],
        cursor: str | None = None,
        size: int = 50,
    ) -> tuple[list[SessionAuditEvent], str | None]:
        """
        Query session-audit events matching the given filters, paginated.

        Args:
            filters: Backend-agnostic filter keys (e.g. org_id, session_id,
                kind, status, event_time range, free-text search term).
            cursor: Opaque pagination cursor from a previous call, or None
                to start from the beginning.
            size: Maximum number of events to return in this page.

        Returns:
            A tuple of (matching events for this page, next cursor or None
            if there are no more pages).
        """
        pass

    @abstractmethod
    async def query_ast(
        self,
        query: dict[str, Any],
        cursor: str | None = None,
        size: int = 50,
    ) -> tuple[list[SessionAuditEvent], str | None]:
        """
        Query session-audit events using a fully-compiled, backend-native
        query clause (see repositories/opensearch_query_compiler.py for the
        OpenSearch case) - the output of compiling a FilterNode AST plus the
        always-injected org_id/retention_days clauses.

        A separate method from `query()` rather than a signature change: the
        existing `filters: dict` shape stays exactly as-is for
        get_session_tree and export_routes.py's current calls, which don't
        need the AST/query-language machinery at all. `query_ast()` is the
        new path used only by the AST-aware search route.

        Same pagination/idempotency contract as `query()`: paginated by
        `cursor`/`size`, returns (events for this page, next cursor or None).
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying connection/client resources on shutdown."""
        pass
