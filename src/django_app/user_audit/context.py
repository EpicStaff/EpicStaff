from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from django.db.models import Model
from django.http import HttpRequest

from user_audit.targets import TargetDescription


@dataclass(frozen=True)
class RowBeforeDelete:
    """The row a DELETE request's URL names, read before the view deletes it.

    Described then, with its parent, because the view may delete with it a row the parent
    is reached through (a RAG reaches its collection through its base type, which the
    delete removes), and afterwards the parent could no longer be read.

    Attributes:
        row: Carries its owning org's id (`ORG_BEFORE_DELETE_ATTRIBUTE` in the middleware).
    """

    row: Model
    description: TargetDescription
    parent: Model | None


@dataclass
class UserActionContext:
    """The request being served, and whether anything recorded an action for it yet.

    Attributes:
        recorded: Set by `record_user_action`; the middleware's fallback records the
            request itself only while it is still False.
        retention_days_by_org: Each org's audit retention, read once per request however
            many actions it records.
        row_before_delete: The row a DELETE request's URL names, loaded and described
            before the view deletes it, so the fallback can still name it afterwards.
    """

    request: HttpRequest
    recorded: bool = False
    retention_days_by_org: dict[int, int] = field(default_factory=dict)
    row_before_delete: RowBeforeDelete | None = None


_current_context: ContextVar[UserActionContext | None] = ContextVar(
    "user_action_context", default=None
)


@contextmanager
def user_action_context(request: HttpRequest) -> Iterator[UserActionContext]:
    """Open the context for one request, and close it whatever happens."""
    context = UserActionContext(request=request)
    token = _current_context.set(context)
    try:
        yield context
    finally:
        _current_context.reset(token)


def mark_request_handled() -> None:
    """Tell the middleware's fallback that this request needed no record, such as a no-op."""
    context = current_context()
    if context is not None:
        context.recorded = True


def current_context() -> UserActionContext | None:
    """The context of the request being served, or None outside a request."""
    return _current_context.get()
