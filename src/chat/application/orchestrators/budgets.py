from dataclasses import dataclass

from domain.enums import BindingStyle, OnResponseTimeout
from domain.errors import BudgetAboveCapError, DurationAboveCapError
from domain.models import Binding, Conversation

BUDGET_FIELDS = ("token_budget_per_conversation", "daily_token_budget")
# The inactivity rules' durations, in seconds.
DURATION_FIELDS = ("response_time_seconds", "close_after_seconds")
_ABOVE_CAP_ERRORS = {
    **dict.fromkeys(BUDGET_FIELDS, BudgetAboveCapError),
    **dict.fromkeys(DURATION_FIELDS, DurationAboveCapError),
}
# What every new desk gets unless it names its own, on any deployment.
NEW_DESK_RULES = {
    "style": BindingStyle.SUPPORT,
    "on_response_timeout": OnResponseTimeout.HANDBACK,
    "handback_message": (
        "Sorry, no one from our team could reply in time. "
        "You can keep chatting with me in the meantime."
    ),
}


@dataclass(frozen=True)
class BindingLimits:
    """What a desk created without them gets, and the most a desk may set: the one source of
    both, for creating a desk and for GET /bindings/limits.

    The deployment sets the token budgets (BUDGET_FIELDS) and the inactivity durations
    (DURATION_FIELDS), a default and a cap each, keyed by field name; NEW_DESK_RULES adds the
    style, the response action and the notice.
    """

    deployment_defaults: dict[str, int]
    caps: dict[str, int]

    @property
    def defaults(self) -> dict[str, object]:
        """Every field a desk created without it gets, keyed by field name."""
        return {**NEW_DESK_RULES, **self.deployment_defaults}

    def with_defaults(self, values: dict) -> dict:
        """`values` with every defaulted field that is absent or None set to its default."""
        return {
            **values,
            **{
                name: default for name, default in self.defaults.items() if values.get(name) is None
            },
        }

    def check(self, values: dict) -> None:
        """Raise for the first limited field in `values` above its cap.

        Raises:
            BudgetAboveCapError: A token budget is above its cap.
            DurationAboveCapError: An inactivity duration is above its cap.
        """
        for name, error in _ABOVE_CAP_ERRORS.items():
            value = values.get(name)
            if value is not None and value > self.caps[name]:
                raise error(name, self.caps[name])


def exhausted_reason(binding: Binding, conversation: Conversation, daily_tokens: int) -> str | None:
    """Which limit stops the next run, or None. Checked before anything is stored.

    The per-conversation limits count today's usage: roll the conversation's usage day first.
    """
    if conversation.turns_today >= binding.max_turns:
        return "max_turns"
    if conversation.tokens_today >= binding.token_budget_per_conversation:
        return "conversation_token_budget"
    if daily_tokens >= binding.daily_token_budget:
        return "daily_token_budget"
    return None


def run_token_budget(binding: Binding) -> int:
    """The run's `token_budget`: the desk's whole per-conversation budget (Django wants at least 1).

    The conversation budget is a soft cap. A run that starts must be able to finish, so it is
    not trimmed to what is left; the cap only blocks the next run (`exhausted_reason`). A
    conversation overshoots by at most one run, which stays finite. The daily desk budget is
    likewise only checked before a run, so with parallel conversations it can overshoot by up to
    one run per conversation.
    """
    return max(1, binding.token_budget_per_conversation)
