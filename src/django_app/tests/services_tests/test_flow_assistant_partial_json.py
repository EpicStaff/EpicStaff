"""Unit tests for partial_json.try_parse_full.

Pure string parsing — the tests themselves touch no tables.
"""

import pytest

from tables.services.flow_assistant.partial_json import try_parse_full


@pytest.mark.parametrize(
    "buffer, expected",
    [
        (
            '{"message": "hi", "ef_tables": [], "action_message": []}',
            {"message": "hi", "ef_tables": [], "action_message": []},
        ),
        ('{"ef_tables": []}', {"ef_tables": []}),
        ("{}", {}),
    ],
)
def test_strict_json_dict_is_returned_unchanged(buffer, expected):
    assert try_parse_full(buffer) == expected


@pytest.mark.parametrize(
    "buffer",
    [
        '```json\n{"message": "hi", "ef_tables": [{"title": "Nodes"}]}\n```',
        '```json {"message": "hi", "ef_tables": [{"title": "Nodes"}]}```',
        '```\n{"message": "hi", "ef_tables": [{"title": "Nodes"}]}\n```',
        '  ```JSON\r\n{"message": "hi", "ef_tables": [{"title": "Nodes"}]}\r\n```  \n',
    ],
)
def test_fenced_json_is_parsed(buffer):
    assert try_parse_full(buffer) == {
        "message": "hi",
        "ef_tables": [{"title": "Nodes"}],
    }


@pytest.mark.parametrize(
    "buffer",
    [
        'Here is the answer:\n{"message": "hi", "action_message": []}',
        '{"message": "hi", "action_message": []}\nLet me know if you need more.',
        'Sure! {"message": "hi", "action_message": []} Hope this helps.',
        'Sure!\n```json\n{"message": "hi", "action_message": []}\n```\nHope this helps.',
    ],
)
def test_json_surrounded_by_prose_is_parsed(buffer):
    assert try_parse_full(buffer) == {"message": "hi", "action_message": []}


def test_braces_inside_message_string_do_not_end_the_object():
    buffer = 'Answer: {"message": "use {var} and }", "ef_tables": []} trailing'

    assert try_parse_full(buffer) == {"message": "use {var} and }", "ef_tables": []}


def test_json_without_message_inside_prose_returns_none():
    assert try_parse_full('Here you go: {"ef_tables": []} done.') is None


@pytest.mark.parametrize(
    "buffer",
    [
        'Here: {"message": null, "ef_tables": []}',
        '{"message": 5} trailing',
        '```json\n{"message": {"text": "hi"}}\n```',
    ],
)
def test_lenient_json_with_non_string_message_returns_none(buffer):
    assert try_parse_full(buffer) is None


def test_fenced_json_without_message_returns_none():
    assert try_parse_full('```json\n{"ef_tables": []}\n```') is None


@pytest.mark.parametrize(
    "buffer",
    [
        '{"message": "Hello", "ef_tables": [',
        '{"message": "Hel',
        '```json\n{"message": "Hello", "ef_tables": [',
        'Here it is: {"message": "Hello"',
    ],
)
def test_truncated_json_returns_none(buffer):
    assert try_parse_full(buffer) is None


@pytest.mark.parametrize(
    "buffer",
    ['["message"]', '"message"', "42", "null", '```json\n["message"]\n```'],
)
def test_non_dict_json_returns_none(buffer):
    assert try_parse_full(buffer) is None


@pytest.mark.parametrize("buffer", ["", "   ", "plain prose with no json at all"])
def test_empty_or_non_json_buffer_returns_none(buffer):
    assert try_parse_full(buffer) is None
