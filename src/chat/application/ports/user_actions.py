import abc
from dataclasses import dataclass
from uuid import UUID

from src.shared.models import UserAction


@dataclass(frozen=True)
class DeskAction:
    """One change an operator made to a desk: who, in which org, which desk under which name.

    Attributes:
        previous_name: The desk's name before a `RENAMED`; None for every other action.
    """

    action: UserAction
    org_id: int
    actor_user_id: int
    desk_id: UUID
    desk_name: str
    previous_name: str | None = None


class AbstractUserActionRecorder(abc.ABC):
    """EpicStaff's user-action audit trail: who changed which desk, and when. Never the content."""

    @abc.abstractmethod
    async def record_desk_action(self, desk_action: DeskAction) -> None:
        """Raises UpstreamUnavailableError when EpicStaff did not take the record."""
