import json

from application.orchestrators.conversation import parse_end_node_result


def test_full_result():
    parsed = parse_end_node_result({"reply": "Hi", "actions": [{"type": "buttons"}], "request_human": True, "extra": 1})
    assert (parsed.reply, parsed.actions, parsed.request_human) == ("Hi", [{"type": "buttons"}], True)


def test_reply_only():
    parsed = parse_end_node_result({"reply": "Hi"})
    assert (parsed.reply, parsed.actions, parsed.request_human) == ("Hi", None, False)


def test_missing_or_invalid_reply_is_none():
    for result in (None, "plain string", 42, [], {"actions": []}, {"reply": None}, {"reply": 5}, {"reply": ""}, {"reply": "  \n "}):
        assert parse_end_node_result(result).reply is None


def test_actions_must_be_a_list():
    assert parse_end_node_result({"reply": "x", "actions": {"type": "buttons"}}).actions is None
    assert parse_end_node_result({"reply": "x", "actions": "nope"}).actions is None


def test_nul_is_dropped_from_the_reply_and_every_string_in_the_actions():
    result = {"reply": "He\x00llo", "actions": [{"ty\x00pe": "butt\x00ons", "options": ["Y\x00es", {"label": ["N\x00o"]}], "count": 2}]}
    parsed = parse_end_node_result(result)
    assert (parsed.reply, parsed.actions) == ("Hello", [{"type": "buttons", "options": ["Yes", {"label": ["No"]}], "count": 2}])


def test_a_reply_of_only_nul_and_whitespace_is_no_reply():
    assert parse_end_node_result({"reply": "\x00 \x00"}).reply is None


def test_a_lone_surrogate_becomes_a_replacement_character_in_the_reply_and_every_string_in_the_actions():
    # What json.loads makes of an unpaired "\ud800" escape; psycopg cannot encode it as UTF-8.
    result = json.loads(r'{"reply": "He\ud800llo", "actions": [{"ty\udc00pe": ["N\ud83do", "x\u0000y"]}]}')
    parsed = parse_end_node_result(result)
    assert (parsed.reply, parsed.actions) == ("He\ufffdllo", [{"ty\ufffdpe": ["N\ufffdo", "xy"]}])


def test_a_surrogate_pair_is_kept():
    assert parse_end_node_result(json.loads(r'{"reply": "\ud83d\ude00"}')).reply == "\U0001f600"


def test_a_pair_sent_as_raw_cesu8_bytes_is_joined_and_a_lone_surrogate_beside_it_replaced():
    # json.loads decodes bytes with "surrogatepass": U+1F600 as CESU-8 arrives as two surrogates.
    body = b'{"reply": "a\xed\xa0\xbd\xed\xb8\x80\xed\xb0\x80", "actions": [{"k\xed\xa0\xbd\\u0000\xed\xb8\x80": "v"}]}'
    result = json.loads(body)
    assert result["reply"] == "a\ud83d\ude00\udc00"
    parsed = parse_end_node_result(result)
    assert (parsed.reply, parsed.actions) == ("a\U0001f600\ufffd", [{"k\U0001f600": "v"}])


def test_actions_nested_deeper_than_the_recursion_limit_are_cleaned():
    # Deeper than the recursion limit (1000), within what the JSON decoder accepts (~2997).
    depth = 2900
    actions: list = ["a\x00"]
    for _ in range(depth):
        actions = [actions]
    cleaned = parse_end_node_result({"reply": "x", "actions": actions}).actions
    for _ in range(depth):
        cleaned = cleaned[0]
    assert cleaned == ["a"]
