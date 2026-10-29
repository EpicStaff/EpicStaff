import json

import pytest
from application.orchestrators.conversation import PublicLimits
from presentation.rest.schemas.public import (
    CreateConversationInput,
    SendMessageInput,
    oversized_objects,
)
from pydantic import ValidationError

LIMITS = PublicLimits(action_max_bytes=2048, extra_data_max_bytes=8192)


def _padded(size: int, filler: str = "a") -> dict:
    """An object whose compact UTF-8 JSON is exactly `size` bytes; `filler` may be multi-byte."""
    overhead = len(json.dumps({"k": ""}, separators=(",", ":")).encode())
    width = len(filler.encode())
    assert (size - overhead) % width == 0
    return {"k": filler * ((size - overhead) // width)}


def _nested(depth: int) -> dict:
    value: dict = {}
    for _ in range(depth - 1):
        value = {"n": value}
    return value


@pytest.mark.parametrize("filler", ["a", "é"])
def test_an_action_at_the_byte_limit_fits_and_one_character_over_is_named(filler):
    assert oversized_objects(LIMITS, action=_padded(2048, filler)) == []
    over = 2048 + len(filler.encode())
    assert oversized_objects(LIMITS, action=_padded(over, filler)) == [
        {"message": f"Must be at most 2048 bytes as compact JSON; got {over}.", "key": "action"}
    ]


def test_chat_extra_data_has_its_own_limit_and_each_object_over_its_limit_is_named():
    assert oversized_objects(LIMITS, chat_extra_data=_padded(8192)) == []
    assert oversized_objects(LIMITS, action=_padded(2048), chat_extra_data=_padded(8193)) == [
        {"message": "Must be at most 8192 bytes as compact JSON; got 8193.", "key": "chat_extra_data"}
    ]
    assert [error["key"] for error in oversized_objects(LIMITS, action=_padded(2049), chat_extra_data=_padded(8193))] == ["action", "chat_extra_data"]
    assert oversized_objects(LIMITS) == []


def test_ten_levels_of_nesting_are_accepted_and_eleven_refused():
    assert SendMessageInput(action=_nested(10)).action
    with pytest.raises(ValidationError, match="nested"):
        SendMessageInput(action=_nested(11))
    with pytest.raises(ValidationError, match="nested"):
        SendMessageInput(content="hi", chat_extra_data={"list": [[[[[[[[[[{}]]]]]]]]]]})


@pytest.mark.parametrize("key", ["__properties__", "__setters__"])
def test_reserved_keys_are_refused_at_any_depth(key):
    with pytest.raises(ValidationError, match=key):
        SendMessageInput(action={"a": {"b": {key: {"x": "1"}}}})
    with pytest.raises(ValidationError, match=key):
        SendMessageInput(content="hi", chat_extra_data={"items": [{"c": {key: {}}}]})
    with pytest.raises(ValidationError, match=key):
        CreateConversationInput(public_key="key", chat_extra_data={key: {}})


@pytest.mark.parametrize("action", [["button"], "button", 3])
def test_an_action_that_is_not_an_object_is_refused(action):
    with pytest.raises(ValidationError):
        SendMessageInput(action=action)


def test_a_message_needs_content_or_an_action():
    with pytest.raises(ValidationError, match="content or an action"):
        SendMessageInput()
    with pytest.raises(ValidationError, match="content or an action"):
        SendMessageInput(action=None, chat_extra_data={"plan": "pro"})


def test_blank_content_with_an_action_is_accepted():
    message = SendMessageInput(content="", action={"type": "button", "id": "yes"})
    assert message.content == "" and message.action == {"type": "button", "id": "yes"}


def test_blank_content_without_an_action_passes_to_the_binding_check():
    # The orchestrator answers 413 for it, as for any content outside the binding's limit.
    assert SendMessageInput(content="   ").content == "   "


@pytest.mark.parametrize("value", [
    {"bad\x00key": 1},
    {"k": "bad\x00value"},
    {"k": [{"deep": ["x", "bad\x00"]}]},
])
def test_nul_in_a_key_or_string_is_refused(value):
    # Postgres JSONB cannot store U+0000; letting it through fails the insert after the run slot is claimed.
    with pytest.raises(ValidationError, match="NUL"):
        SendMessageInput(action=value)
    with pytest.raises(ValidationError, match="NUL"):
        SendMessageInput(content="hi", chat_extra_data=value)
    with pytest.raises(ValidationError, match="NUL"):
        CreateConversationInput(public_key="key", chat_extra_data=value)


def test_nul_in_content_is_refused():
    with pytest.raises(ValidationError, match="NUL"):
        SendMessageInput(content="hi\x00there")
