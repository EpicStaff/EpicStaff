import itertools
import secrets

from common.utils import new_id, utc_today, utcnow
from domain.enums import BindingStyle, CloseReason, ConversationStatus, IdentityMode, Mode, OnBudgetExhausted, OnResponseTimeout, RunState
from domain.models import Binding, Conversation

# Factory rows skip the counter table; numbering them from a million keeps them clear of the
# numbers a test's real creates draw from it on the same binding.
_visitor_numbers = itertools.count(1_000_000)
# The holder a factory `human` row gets unless the test names one: the database requires one.
FACTORY_OPERATOR_ID = 1
HANDBACK_NOTICE = "Sorry for the wait; back to the bot."


def make_binding(org_id=1, graph_id=1, name="Binding", **overrides) -> Binding:
    """A live desk with a new desk's inactivity rules: Support, hand back after 10 min, close after 24 h."""
    now = utcnow()
    values = dict(
        id=new_id(), org_id=org_id, graph_id=graph_id, name=name,
        bot_display_name="Bot", operator_display_name="Support",
        public_key=secrets.token_urlsafe(24), allowed_origins=["https://example.com"],
        identity_mode=IdentityMode.ANONYMOUS, identity_secret=None, is_active=True,
        history_window=20, max_message_length=4000, max_turns=200,
        token_budget_per_conversation=200_000, daily_token_budget=1_000_000, messages_per_minute=10,
        on_budget_exhausted=OnBudgetExhausted.REPLY, budget_exhausted_message="Budget exhausted.",
        handoff_enabled=True, broken_reason=None, contract_errors=[], created_at=now, updated_at=now,
        style=BindingStyle.SUPPORT, response_time_seconds=600, on_response_timeout=OnResponseTimeout.HANDBACK,
        handback_message=HANDBACK_NOTICE, close_after_seconds=86_400,
    )
    return Binding(**{**values, **overrides})


def make_conversation(binding: Binding, subject: str | None = None, mode="bot", **overrides) -> Conversation:
    """A row the database accepts for `mode`: handed off unless bot, waiting while awaiting_human, held while human."""
    mode = Mode(mode)
    handoff_at = None if mode == Mode.BOT else utcnow()
    values = dict(
        id=new_id(), binding_id=binding.id, org_id=binding.org_id,
        subject=subject or secrets.token_urlsafe(8), visitor_number=next(_visitor_numbers),
        is_test=False, mode=mode, assigned_operator_id=FACTORY_OPERATOR_ID if mode == Mode.HUMAN else None,
        run_state=RunState.IDLE, active_run_id=None, active_since=None, tokens_used=0, turns=0,
        usage_day=utc_today(), tokens_today=0, turns_today=0,
        last_message_at=None, last_message_preview="", handoff_reason="", created_at=utcnow(),
        handoff_at=handoff_at,
        visitor_waiting_since=handoff_at if mode == Mode.AWAITING_HUMAN else None,
    )
    return Conversation(**{**values, **overrides})


def make_closed(binding: Binding, reason=CloseReason.INACTIVE, mode="bot", **overrides) -> Conversation:
    """A closed row the database accepts: nobody waits, no run, and an operator named only when resolved.

    The mode, hand-off and holder stay as `make_conversation` gives them for `mode`, as a close keeps them.
    """
    reason = CloseReason(reason)
    values = dict(
        status=ConversationStatus.CLOSED, close_reason=reason, closed_at=utcnow(),
        closed_by_user_id=FACTORY_OPERATOR_ID if reason == CloseReason.RESOLVED else None,
        visitor_waiting_since=None,
    )
    return make_conversation(binding, mode=mode, **{**values, **overrides})
