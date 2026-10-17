from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

import pytest
from domain.enums import BindingStyle, CloseReason, ConversationStatus, Mode, OnResponseTimeout, Role
from domain.models import Binding, Conversation
from infrastructure.database.mappers import to_domain, values_of
from tests.factories import make_binding, make_closed, make_conversation


@pytest.mark.parametrize("role", [Role.OPERATOR, None])
def test_an_optional_enum_loads_as_the_enum_and_none_stays_none(role):
    conversation = make_conversation(make_binding(), mode="human", last_message_role=role)
    row = SimpleNamespace(**values_of(conversation))  # what the database hands back: plain strings
    assert row.last_message_role == (role.value if role else None) and not isinstance(row.last_message_role, Role)
    loaded = to_domain(row, Conversation)
    assert loaded == conversation
    assert loaded.last_message_role is role and loaded.mode is Mode.HUMAN


@dataclass
class _Shapes:
    plain: Mode
    optional: Role | None
    typing_optional: Optional[Role]  # noqa: UP045 - the typing spelling must unwrap too
    roles: list[Role]
    either: Role | Mode


def test_only_a_plain_or_optional_enum_is_converted():
    row = SimpleNamespace(plain="bot", optional="user", typing_optional=None, roles=["operator", "user"], either="human")
    loaded = to_domain(row, _Shapes)
    assert loaded.plain is Mode.BOT and loaded.optional is Role.USER and loaded.typing_optional is None
    # A container or an ambiguous union is passed through as stored, never fed to an enum constructor.
    assert loaded.roles == ["operator", "user"] and loaded.either == "human" and type(loaded.either) is str


@pytest.mark.parametrize("reason", list(CloseReason))
def test_a_closed_conversation_loads_its_status_and_reason_as_enums(reason):
    closed = make_closed(make_binding(), reason=reason, mode="human")
    row = SimpleNamespace(**values_of(closed))
    assert (row.status, row.close_reason) == ("closed", reason.value)
    loaded = to_domain(row, Conversation)
    assert loaded == closed and loaded.status is ConversationStatus.CLOSED and loaded.close_reason is reason


def test_an_open_conversation_loads_no_close_reason():
    loaded = to_domain(SimpleNamespace(**values_of(make_conversation(make_binding()))), Conversation)
    assert (loaded.status, loaded.close_reason, loaded.closed_at) == (ConversationStatus.OPEN, None, None)


def test_a_desks_style_and_response_action_load_as_enums():
    binding = make_binding(style=BindingStyle.ONGOING, on_response_timeout=OnResponseTimeout.OVERDUE)
    loaded = to_domain(SimpleNamespace(**values_of(binding)), Binding)
    assert loaded == binding and loaded.style is BindingStyle.ONGOING and loaded.on_response_timeout is OnResponseTimeout.OVERDUE
