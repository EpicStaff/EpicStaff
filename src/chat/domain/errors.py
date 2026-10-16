__all__ = [
    "AliasReservedError",
    "AliasTakenError",
    "BindingBrokenError",
    "BindingInactiveError",
    "BotNameTakenError",
    "BudgetAboveCapError",
    "CallbackRejectedError",
    "ChatError",
    "ClaimedByOtherError",
    "ContractFailedError",
    "ConversationClosedError",
    "DurationAboveCapError",
    "FlowForbiddenError",
    "FlowNotFoundError",
    "FlowStartError",
    "FlowUnavailableError",
    "ForbiddenError",
    "InvalidCursorError",
    "InvalidIdentityError",
    "InvalidSearchError",
    "InvalidTokenError",
    "MessageTooLongError",
    "NotAssignedError",
    "NotFoundError",
    "NotMemberError",
    "OriginNotAllowedError",
    "RateLimitedError",
    "RunInProgressError",
    "RunNotFoundError",
    "SessionMismatchError",
    "UnknownFlowError",
    "UnknownRunError",
    "UpstreamUnavailableError",
]


class ChatError(Exception):
    """Base of every error the REST layer turns into `{code, message}`."""

    code = "internal_error"
    status_code = 500
    default_message = ""

    def __init__(self, message: str = "", /, **extra):
        super().__init__(message or self.default_message)
        self.extra = extra

    @property
    def message(self) -> str:
        return str(self)


class InvalidTokenError(ChatError):
    code, status_code, default_message = "invalid_token", 401, "Unknown or revoked visitor token."


class InvalidIdentityError(ChatError):
    code, status_code, default_message = (
        "invalid_identity",
        401,
        "Identity token missing, expired or badly signed.",
    )


class CallbackRejectedError(ChatError):
    code, status_code, default_message = (
        "invalid_signature",
        401,
        "Callback signature or timestamp rejected.",
    )


class ForbiddenError(ChatError):
    code, status_code, default_message = "forbidden", 403, "Missing permission."


class FlowForbiddenError(ChatError):
    code, status_code, default_message = (
        "flow_forbidden",
        403,
        "flows:read is required to bind this flow.",
    )


class OriginNotAllowedError(ChatError):
    code, status_code, default_message = (
        "origin_not_allowed",
        403,
        "Origin is not allowed on this binding.",
    )


class NotFoundError(ChatError):
    code, status_code, default_message = "not_found", 404, "Not found."


class UnknownRunError(ChatError):
    code, status_code, default_message = "unknown_run", 404, "No run with this id."


class SessionMismatchError(ChatError):
    code, status_code, default_message = (
        "session_mismatch",
        409,
        "The callback names another session than the one this run is bound to.",
    )


class RunInProgressError(ChatError):
    code, status_code, default_message = "run_in_progress", 409, "A reply is still being produced."


class ClaimedByOtherError(ChatError):
    code, status_code, default_message = (
        "claimed_by_other",
        409,
        "Another operator holds this conversation.",
    )


class NotAssignedError(ChatError):
    code, status_code, default_message = (
        "not_assigned",
        409,
        "Only the assigned operator can reply, and only in human mode.",
    )


class ConversationClosedError(ChatError):
    code, status_code, default_message = (
        "conversation_closed",
        409,
        "The conversation is closed; a new message needs a new conversation.",
    )

    def __init__(self, close_reason: str):
        super().__init__(close_reason=close_reason)


class BindingInactiveError(ChatError):
    code, status_code, default_message = "binding_inactive", 410, "The binding was switched off."


class MessageTooLongError(ChatError):
    code, status_code, default_message = "message_too_long", 413, "Message is empty or too long."


class RateLimitedError(ChatError):
    code, status_code, default_message = "rate_limited", 429, "Too many messages."

    def __init__(self, retry_after: int):
        super().__init__(retry_after=retry_after)


class AliasTakenError(ChatError):
    code, status_code, default_message = (
        "alias_taken",
        409,
        "Another operator on this desk already uses this name.",
    )


class AliasReservedError(ChatError):
    code, status_code, default_message = (
        "alias_reserved",
        409,
        "This is the desk's bot name; visitors could not tell you apart.",
    )


class BotNameTakenError(ChatError):
    code, status_code, default_message = (
        "bot_name_taken",
        409,
        (
            "An operator on this desk already uses this name; visitors could not tell the bot "
            "from them. Choose another bot name."
        ),
    )

    def __init__(self):
        super().__init__(field="bot_display_name")


class InvalidCursorError(ChatError):
    code, status_code, default_message = "invalid_cursor", 400, "The page cursor is malformed."


class InvalidSearchError(ChatError):
    code, status_code, default_message = "invalid_search", 400, "The search is not valid."


class NotATestConversationError(ChatError):
    code, status_code, default_message = (
        "not_a_test_conversation",
        400,
        "Visitor tokens are issued to operators only for test conversations.",
    )


class UnknownFlowError(ChatError):
    code, status_code, default_message = (
        "unknown_flow",
        400,
        "The flow does not exist in this organization.",
    )


class BudgetAboveCapError(ChatError):
    code, status_code = "budget_above_cap", 400

    def __init__(self, field: str, cap: int):
        super().__init__(f"`{field}` cannot exceed {cap} on this deployment.", field=field, max=cap)


class DurationAboveCapError(ChatError):
    code, status_code = "duration_above_cap", 400

    def __init__(self, field: str, cap: int):
        super().__init__(
            f"`{field}` cannot exceed {cap} seconds on this deployment.", field=field, max=cap
        )


class ContractFailedError(ChatError):
    code, status_code, default_message = "contract_failed", 400, "The flow cannot serve chat."

    def __init__(self, errors: list[str]):
        super().__init__(contract_errors=errors)


class BindingBrokenError(ChatError):
    code, status_code, default_message = "binding_broken", 503, "The flow behind this chat is gone."


class FlowUnavailableError(ChatError):
    code, status_code, default_message = "flow_unavailable", 503, "The flow could not be started."


class UpstreamUnavailableError(ChatError):
    code, status_code, default_message = (
        "upstream_unavailable",
        503,
        "EpicStaff could not be reached.",
    )


# Port-level errors: raised by adapters, translated by orchestrators, never reach HTTP as-is.
class FlowNotFoundError(Exception):
    """Django answered 404 for the graph."""


class FlowStartError(Exception):
    """Django refused or failed to start the run (anything but 201 and 404)."""


class RunNotFoundError(Exception):
    """Django answered 404 for the session."""


class NotMemberError(Exception):
    """Django refused the org header for this user."""
