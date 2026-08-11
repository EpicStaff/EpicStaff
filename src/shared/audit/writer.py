import uuid
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from loguru import logger

if TYPE_CHECKING:
    from src.shared.audit.client import AuditClient


class AuditEventLike(Protocol):
    """
    Structural contract any audit-domain event must satisfy to flow through
    this shared plumbing - a stable `id` (the dedup key every AuditClient/
    repository relies on) plus pydantic's model_dump. SessionAuditEvent
    satisfies this today; a future UserActionEvent does too, without either
    needing to inherit from a shared base model.
    """

    id: str

    def model_dump(self, *, mode: str = ...) -> dict[str, Any]: ...


T = TypeVar("T", bound=AuditEventLike)


def derive_root_id(namespace: uuid.UUID, key: str) -> str:
    """
    Deterministic id for a domain's 'root' record (e.g. a session), so any
    process can compute the same id from the natural key alone, with zero
    coordination.
    """
    return str(uuid.uuid5(namespace, key))


async def safe_emit(client: "AuditClient[T]", event: T) -> None:
    """Never raises - an audit failure must never affect the caller's primary work."""
    try:
        await client.emit(event)
    except Exception as e:
        logger.warning(f"Audit emit failed, dropping event {event.id}: {e}")
