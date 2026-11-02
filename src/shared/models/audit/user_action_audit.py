from enum import StrEnum

from .base import BaseAuditEvent


class UserAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    RENAMED = "renamed"
    DELETED = "deleted"
    RESTORED = "restored"
    PERMANENTLY_DELETED = "permanently_deleted"
    SIGNED_IN = "signed_in"
    SIGN_IN_FAILED = "sign_in_failed"
    SIGNED_OUT = "signed_out"
    PASSWORD_RESET = "password_reset"


class UserActionEvent(BaseAuditEvent):
    """One action a user (or an API key) took, as it was at the time it happened.

    Attributes:
        number: Short record number from one deployment-wide sequence, increasing with
            each record but with gaps. Every record sent now carries one; it is None only
            on records stored before numbering existed. `id` stays the unique key.
        actor_email: Email at the time of the action; empty for the system API key.
        action: A UserAction value, or a custom DRF action name ("copy") for fallback records.
        target_type: Display label such as "python node", "flow" or "member".
        previous_name: Set only when action is "renamed".
        route: Fallback records only, e.g. "POST api/graphs/<pk>/copy/".
    """

    number: int | None = None
    actor_user_id: int | None
    actor_email: str
    actor_api_key_name: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    previous_name: str | None = None
    parent_type: str | None = None
    parent_id: str | None = None
    parent_name: str | None = None
    route: str | None = None
