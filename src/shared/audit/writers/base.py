import uuid
from abc import ABC, abstractmethod
from typing import Generic

from loguru import logger

from src.shared.audit.client import AuditClient
from src.shared.audit.protocols import T


def derive_root_id(namespace: uuid.UUID, key: str) -> str:
    """
    Deterministic id for a domain's 'root' record (e.g. a session), so any
    process can compute the same id from the natural key alone, with zero
    coordination.
    """
    return str(uuid.uuid5(namespace, key))


async def safe_emit(client: AuditClient[T], event: T) -> None:
    """Never raises - an audit failure must never affect the caller's primary work."""
    try:
        await client.emit(event)
    except Exception as e:
        logger.warning(f"Audit emit failed, dropping event {event.id}: {e}")


class BaseAuditWriter(ABC, Generic[T]):
    """
    Shared plumbing every domain writer gets for free: owns the client,
    knows how to emit safely, and shuts it down. To add a domain writer:
    subclass BaseAuditWriter[YourEvent] and implement add_custom_message -
    see src/shared/audit/writers/session_writer.py for the worked example,
    and src/auditor/app/domains/README.md for the consumer-side mirror of
    this same per-domain-plugin shape.
    """

    def __init__(self, client: AuditClient[T]):
        self._client = client

    async def _emit(self, event: T) -> None:
        await safe_emit(self._client, event)

    async def shutdown(self) -> None:
        """Delegates to the underlying AuditClient's best-effort drain-and-flush."""
        await self._client.shutdown()

    @abstractmethod
    async def add_custom_message(
        self, *, org_id: int, event_id: str, details: dict, **kwargs
    ) -> None: ...
