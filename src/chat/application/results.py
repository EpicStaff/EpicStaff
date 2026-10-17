from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from domain.enums import SubmitState


@dataclass(frozen=True)
class SubmitResult:
    message_id: UUID
    state: SubmitState


class ApplyOutcome(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


@dataclass(frozen=True)
class EndResult:
    reply: str | None
    actions: list | None
    request_human: bool
