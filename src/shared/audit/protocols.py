from typing import Protocol, TypeVar, Any


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
