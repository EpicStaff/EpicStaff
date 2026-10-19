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
