"""Unit tests for partial_json: try_parse_full and MessageFieldStream.

Pure string parsing — the tests themselves touch no tables.
"""

import pytest

from tables.services.flow_assistant.partial_json import MessageFieldStream, try_parse_full


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


# ── MessageFieldStream: the message value decoded from a document fed in chunks ──

_STREAMED_DOCUMENTS = [
    pytest.param('{"message": "hello", "ef_tables": []}', "hello", id="plain"),
    pytest.param('{ "message" :\n\t"spaced" }', "spaced", id="whitespace-around-colon"),
    pytest.param(r'{"message": "say \"hi\""}', 'say "hi"', id="escaped-quote"),
    pytest.param(r'{"message": "back\\slash"}', r"back\slash", id="escaped-backslash"),
    pytest.param(r'{"message": "a\nb\tc\rd\/e\bf\fg"}', "a\nb\tc\rd/e\bf\fg", id="simple-escapes"),
    pytest.param(r'{"message": "caf\u00e9 \u20ac"}', "caf\u00e9 \u20ac", id="unicode-escape"),
    pytest.param(r'{"message": "bad \uZZZZ end"}', r"bad \uZZZZ end", id="malformed-unicode-escape"),
    pytest.param(r'{"message": "odd \q"}', "odd q", id="unknown-escape"),
    pytest.param('{"message": "end"} "message": "again"', "end", id="text-after-closing-quote"),
    pytest.param('{"message": ""}', "", id="empty-value"),
    pytest.param('{"ef_tables": [], "action_message": []}', "", id="missing-key"),
    pytest.param('{"message": null}', "", id="non-string-value"),
    pytest.param('{"message" "no colon"}', "", id="missing-colon"),
    pytest.param('{"message": "unterminated \\', "unterminated ", id="dangling-backslash"),
    pytest.param(r'{"message": "unterminated \u00', "unterminated ", id="dangling-unicode-escape"),
]


@pytest.mark.parametrize("document, expected_message", _STREAMED_DOCUMENTS)
def test_whole_document_fed_at_once_decodes_the_message(document, expected_message):
    assert MessageFieldStream().feed(document) == expected_message


@pytest.mark.parametrize("document, expected_message", _STREAMED_DOCUMENTS)
def test_document_split_at_any_position_decodes_the_same_message(document, expected_message):
    for split_position in range(len(document) + 1):
        message_stream = MessageFieldStream()
        decoded = message_stream.feed(document[:split_position]) + message_stream.feed(
            document[split_position:]
        )
        assert decoded == expected_message, f"split at {split_position}"


@pytest.mark.parametrize("chunk_length", [1, 3, 7])
@pytest.mark.parametrize("document, expected_message", _STREAMED_DOCUMENTS)
def test_document_fed_in_fixed_chunks_decodes_the_same_message(
    document, expected_message, chunk_length
):
    message_stream = MessageFieldStream()
    decoded = "".join(
        message_stream.feed(document[index : index + chunk_length])
        for index in range(0, len(document), chunk_length)
    )
    assert decoded == expected_message


def test_each_chunk_returns_only_its_own_part_of_the_message():
    message_stream = MessageFieldStream()

    deltas = [
        message_stream.feed(chunk)
        for chunk in ['{"mess', 'age": "he', "llo \\", 'u00e9!', '"}', ', "x": "y"}']
    ]

    assert deltas == ["", "he", "llo ", "é!", "", ""]


def test_empty_chunk_returns_nothing():
    message_stream = MessageFieldStream()
    message_stream.feed('{"message": "ab')

    assert message_stream.feed("") == ""
    assert message_stream.feed('c"}') == "c"
