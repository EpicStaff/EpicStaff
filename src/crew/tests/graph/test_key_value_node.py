import json
import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from dotdict import DotDict

from clients.errors import ClientValidationError
from services.graph.exceptions import KeyValueNodeError
from services.graph.nodes import key_value_node
from services.graph.nodes.key_value_node import KeyValueNode

TABLE_NAME = "Customers"


def read_response(values: dict) -> dict:
    return {"values": values, "table_name": TABLE_NAME}


def delete_response(values: dict) -> dict:
    return {"deleted": len(values), "values": values, "table_name": TABLE_NAME}


def make_client(created: list[str] | None = None) -> AsyncMock:
    """A client whose calls return Django's response shapes."""
    client = AsyncMock()
    client.read.return_value = read_response({})
    client.write.return_value = {"written": 0, "created": created or [], "table_name": TABLE_NAME}
    client.delete.return_value = delete_response({})
    return client


def key_value_messages(writer: MagicMock) -> list[dict]:
    return [
        call.args[0].message_data
        for call in writer.call_args_list
        if isinstance(call.args[0].message_data, dict)
        and call.args[0].message_data.get("message_type") == "key_value"
    ]


def make_node(
    mode: str,
    entries: list[dict],
    client=None,
    table_id: int | None = 3,
) -> KeyValueNode:
    return KeyValueNode(
        session_id=7,
        node_name="persist_1",
        stop_event=MagicMock(),
        key_value_table_id=table_id,
        mode=mode,
        entries=entries,
        key_value_client=client or make_client(),
    )


def make_state(variables: dict) -> dict:
    return {"state_history": [], "variables": DotDict(variables), "system_variables": {}}


async def run(node: KeyValueNode, variables: dict):
    return await node.execute(
        state=make_state(variables), writer=MagicMock(), execution_order=0, input_={}
    )


@pytest.mark.asyncio
async def test_read_writes_stored_values_to_target_paths_and_none_for_missing_keys():
    client = make_client()
    client.read.return_value = read_response({"profile_42": {"name": "Ann"}, "stored_null": None})
    node = make_node("read", [
        {"key": "profile_{variables.user_id}", "value": "variables.user.profile"},
        {"key": "score_{variables.user_id}", "value": "variables.score"},
        {"key": "stored_null", "value": "variables.nothing"},
    ], client)
    state = make_state({"user_id": 42, "score": 5})

    result = await node.execute(state=state, writer=MagicMock(), execution_order=0, input_={})

    assert state["variables"].deep_dump() == {
        "user_id": 42,
        "user": {"profile": {"name": "Ann"}},
        "score": None,
        "nothing": None,
    }
    assert result == {
        "variables.user.profile": {"name": "Ann"},
        "variables.score": None,
        "variables.nothing": None,
    }
    session_id, table_id, keys = client.read.await_args.args
    assert (session_id, table_id) == (7, 3)
    assert keys == ["profile_42", "score_42", "stored_null"]


@pytest.mark.asyncio
async def test_read_writes_into_existing_list_item():
    client = make_client()
    client.read.return_value = read_response({"k": "Ann"})
    node = make_node("read", [{"key": "k", "value": "variables.users[1].name"}], client)
    state = make_state({"users": [{"name": "a"}, {"name": "b"}]})

    await node.execute(state=state, writer=MagicMock(), execution_order=0, input_={})

    assert state["variables"].deep_dump() == {"users": [{"name": "a"}, {"name": "Ann"}]}


@pytest.mark.asyncio
async def test_read_through_run_writes_only_target_paths():
    client = make_client()
    client.read.return_value = read_response({"k": 1})
    node = make_node("read", [{"key": "k", "value": "variables.count"}], client)
    state = make_state({"out": "untouched"})

    await node.run(state, MagicMock())

    assert node.output_variable_path is None
    assert state["variables"].deep_dump() == {"out": "untouched", "count": 1}


@pytest.mark.asyncio
async def test_read_replaces_existing_object_instead_of_merging():
    client = make_client()
    client.read.return_value = read_response({"k": {"name": "Ann"}})
    node = make_node("read", [{"key": "k", "value": "variables.user"}], client)
    state = make_state({"user": {"id": 1, "stale": True}})

    await node.execute(state=state, writer=MagicMock(), execution_order=0, input_={})

    assert state["variables"].deep_dump() == {"user": {"name": "Ann"}}


@pytest.mark.asyncio
async def test_read_targets_sharing_only_a_name_prefix_do_not_overlap():
    client = make_client()
    client.read.return_value = read_response({"k1": {"id": 1}, "k2": "ann"})
    node = make_node(
        "read",
        [{"key": "k1", "value": "variables.user"}, {"key": "k2", "value": "variables.username"}],
        client,
    )
    state = make_state({})

    await node.execute(state=state, writer=MagicMock(), execution_order=0, input_={})

    assert state["variables"].deep_dump() == {"user": {"id": 1}, "username": "ann"}


@pytest.mark.asyncio
async def test_read_same_key_into_two_targets_reads_it_once():
    client = make_client()
    client.read.return_value = read_response({"k": "Ann"})
    node = make_node(
        "read",
        [{"key": "k", "value": "variables.a"}, {"key": "k", "value": "variables.b"}],
        client,
    )
    state = make_state({})

    await node.execute(state=state, writer=MagicMock(), execution_order=0, input_={})

    assert state["variables"].deep_dump() == {"a": "Ann", "b": "Ann"}
    client.read.assert_awaited_once_with(7, 3, ["k"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("profile_{variables.user.id}_{variables.tags[1]}", "profile_42_y"),
        ("p_{ variables.user.id }", "p_42"),
    ],
    ids=["nested-path-and-list-index", "surrounding-spaces"],
)
async def test_key_placeholders_are_rendered_from_the_state(key, expected):
    client = make_client()
    node = make_node("read", [{"value": "variables.out", "key": key}], client)

    await run(node, {"user": {"id": 42}, "tags": ["x", "y"]})

    client.read.assert_awaited_once_with(7, 3, [expected])


@pytest.mark.asyncio
async def test_key_placeholder_value_with_braces_is_rejected():
    client = make_client()
    node = make_node("read", [{"value": "variables.out", "key": "profile_{variables.name}"}], client)

    with pytest.raises(KeyValueNodeError) as error:
        await run(node, {"name": "a{b}"})

    assert str(error.value) == (
        "Key-Value node 'persist_1': key 'profile_{variables.name}' resolved to "
        f"'profile_a{{b}}', which is not a valid key: {key_value_node.KEY_RULE}."
    )
    client.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_sends_rendered_keys_and_state_path_values():
    client = make_client()
    node = make_node(
        "write", [{"key": "profile_{variables.user.id}", "value": "variables.user.profile"}], client
    )

    result = await run(node, {"user": {"id": 42, "profile": {"name": "Ann"}}})

    client.write.assert_awaited_once_with(7, 3, {"profile_42": {"name": "Ann"}})
    assert result == {"profile_42": {"name": "Ann"}}


@pytest.mark.asyncio
async def test_write_value_default_applies_when_path_is_missing():
    client = make_client()
    node = make_node("write", [{"key": "count", "value": "variables.count|0"}], client)

    await run(node, {})

    client.write.assert_awaited_once_with(7, 3, {"count": 0})


@pytest.mark.asyncio
async def test_write_value_null_default_writes_null_when_path_is_missing():
    client = make_client()
    node = make_node("write", [{"key": "count", "value": "variables.count|null"}], client)

    result = await run(node, {})

    client.write.assert_awaited_once_with(7, 3, {"count": None})
    assert result == {"count": None}


@pytest.mark.asyncio
async def test_write_value_default_does_not_apply_when_path_holds_null():
    client = make_client()
    node = make_node("write", [{"key": "count", "value": "variables.count|0"}], client)

    await run(node, {"count": None})

    client.write.assert_awaited_once_with(7, 3, {"count": None})


@pytest.mark.asyncio
async def test_write_value_inside_a_null_variable_with_default_writes_the_default():
    client = make_client()
    node = make_node("write", [{"key": "k", "value": "variables.nothing.first|0"}], client)

    await run(node, {"nothing": None})

    client.write.assert_awaited_once_with(7, 3, {"k": 0})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "values",
    [
        ("variables.a", "variables.a"),
        ("variables.a", "variables.a|0"),
        ("variables.a|0", "variables.a|1"),
    ],
)
async def test_write_stores_one_source_under_every_key_that_names_it(values):
    client = make_client()
    node = make_node(
        "write",
        [{"key": "k1", "value": values[0]}, {"key": "k2", "value": values[1]}],
        client,
    )
    await run(node, {"a": 1})
    client.write.assert_awaited_once_with(7, 3, {"k1": 1, "k2": 1})


@pytest.mark.asyncio
async def test_write_accepts_a_source_that_is_nested_in_another():
    client = make_client()
    node = make_node(
        "write",
        [{"key": "k1", "value": "variables.user"}, {"key": "k2", "value": "variables.user.id"}],
        client,
    )
    await run(node, {"user": {"id": 1}})
    client.write.assert_awaited_once_with(7, 3, {"k1": {"id": 1}, "k2": 1})


@pytest.mark.asyncio
async def test_write_with_null_value_writes_null():
    client = make_client(created=["k"])
    node = make_node("write", [{"key": "k", "value": "variables.profile"}], client)
    writer = MagicMock()

    result = await node.execute(
        state=make_state({"profile": None}), writer=writer, execution_order=0, input_={}
    )

    client.write.assert_awaited_once_with(7, 3, {"k": None})
    assert result == {"k": None}
    [message] = key_value_messages(writer)
    assert message["entries"] == [
        {"key": "k", "path": "variables.profile", "found": None, "created": True,
         "value": None, "truncated": False},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value_path", "variables"),
    [
        ("variables.user.middle_name", {"user": {"middle_name": None}}),
        ("variables.users[1].middle_name", {"users": [{}, {"middle_name": None}]}),
        ("variables.middle_names[0]", {"middle_names": [None]}),
    ],
)
async def test_write_with_nested_null_value_writes_null(value_path, variables):
    client = make_client()
    node = make_node("write", [{"key": "k", "value": value_path}], client)

    await run(node, variables)

    client.write.assert_awaited_once_with(7, 3, {"k": None})


@pytest.mark.asyncio
async def test_delete_sends_rendered_keys():
    client = make_client()
    node = make_node("delete", [{"key": "session_{variables.id}"}, {"key": "static"}], client)
    assert await run(node, {"id": 5}) is None
    client.delete.assert_awaited_once_with(7, 3, ["session_5", "static"])


@pytest.mark.asyncio
async def test_render_key_rejects_too_long_key():
    node = make_node("read", [{"value": "variables.out", "key": "{variables.long}"}])
    with pytest.raises(KeyValueNodeError) as error:
        await run(node, {"long": "x" * 513})
    assert str(error.value) == (
        "Key-Value node 'persist_1': key '{variables.long}' resolved to "
        f"'{'x' * 100}…', which is not a valid key: use only letters, digits and _, "
        "don't start with a digit, and keep it to at most 512 characters."
    )


# Keep identical to the resolved-key parity table in Django's
# tests/services_tests/test_key_value_table_service.py.
VALID_RESOLVED_KEYS = ["k", "_", "user_42", "a" * 512]
INVALID_RESOLVED_KEYS = [
    "",
    "4_user",
    "user_4 2",
    "user_-1",
    "user_1.5",
    "user_é",
    "a{b}",
    "k\n",
    "a" * 513,
]


def one_entry(mode: str, key: str) -> list[dict]:
    return [{"key": key}] if mode == "delete" else [{"key": key, "value": "variables.source"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
@pytest.mark.parametrize("resolved", VALID_RESOLVED_KEYS)
async def test_valid_resolved_key_is_sent_to_the_table(mode, resolved):
    client = make_client()
    node = make_node(mode, one_entry(mode, "{variables.key}"), client)

    await run(node, {"key": resolved, "source": 1})

    getattr(client, mode).assert_awaited_once()
    sent = getattr(client, mode).await_args.args[2]
    assert list(sent) == [resolved]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
@pytest.mark.parametrize("resolved", INVALID_RESOLVED_KEYS)
async def test_invalid_resolved_key_is_rejected_before_calling_the_table(mode, resolved):
    client = make_client()
    node = make_node(mode, one_entry(mode, "{variables.key}"), client)

    with pytest.raises(KeyValueNodeError) as error:
        await run(node, {"key": resolved, "source": 1})

    shown = resolved if len(resolved) <= 100 else f"{resolved[:100]}…"
    assert str(error.value) == (
        f"Key-Value node 'persist_1': key '{{variables.key}}' resolved to {shown!r}, "
        f"which is not a valid key: {key_value_node.KEY_RULE}."
    )
    getattr(client, mode).assert_not_awaited()


@pytest.mark.asyncio
async def test_read_emits_message_with_found_and_missing_entries():
    client = make_client()
    client.read.return_value = read_response({"k1": {"name": "Ann"}, "stored_null": None})
    node = make_node("read", [
        {"key": "k1", "value": "variables.a"},
        {"key": "missing", "value": "variables.b"},
        {"key": "stored_null", "value": "variables.c"},
    ], client)
    writer = MagicMock()

    await node.execute(state=make_state({}), writer=writer, execution_order=0, input_={})

    assert key_value_messages(writer) == [{
        "mode": "read",
        "table_id": 3,
        "table_name": "Customers",
        "entries": [
            {"key": "k1", "path": "variables.a", "found": True, "created": None,
             "value": {"name": "Ann"}, "truncated": False},
            {"key": "missing", "path": "variables.b", "found": False, "created": None,
             "value": None, "truncated": False},
            {"key": "stored_null", "path": "variables.c", "found": True, "created": None,
             "value": None, "truncated": False},
        ],
        "deleted_count": None,
        "message_type": "key_value",
    }]
    message = writer.call_args_list[-1].args[0]
    assert (message.session_id, message.name) == (7, "persist_1")


@pytest.mark.asyncio
async def test_write_emits_message_with_created_flags_and_source_paths():
    client = make_client(created=["new"])
    node = make_node("write", [
        {"key": "new", "value": "variables.a"},
        {"key": "old_{variables.id}", "value": "variables.missing|fallback"},
    ], client)
    writer = MagicMock()

    output = await node.execute(
        state=make_state({"a": "Ann", "id": 1}), writer=writer, execution_order=0, input_={}
    )

    assert output == {"new": "Ann", "old_1": "fallback"}
    [message] = key_value_messages(writer)
    assert message["mode"] == "write"
    assert message["table_name"] == "Customers"
    assert message["entries"] == [
        {"key": "new", "path": "variables.a", "found": None, "created": True,
         "value": "Ann", "truncated": False},
        {"key": "old_1", "path": "variables.missing|fallback", "found": None, "created": False,
         "value": "fallback", "truncated": False},
    ]


@pytest.mark.asyncio
async def test_delete_emits_message_with_deleted_values_and_missing_keys():
    client = make_client()
    client.delete.return_value = delete_response({"b": {"name": "Ann"}, "stored_null": None})
    node = make_node(
        "delete",
        [{"key": "b"}, {"key": "a"}, {"key": "b"}, {"key": "stored_null"}],
        client,
    )
    writer = MagicMock()

    output = await node.execute(state=make_state({}), writer=writer, execution_order=0, input_={})

    assert output is None
    assert key_value_messages(writer) == [{
        "mode": "delete",
        "table_id": 3,
        "table_name": "Customers",
        "entries": [
            {"key": "a", "path": None, "found": False, "created": None,
             "value": None, "truncated": False},
            {"key": "b", "path": None, "found": True, "created": None,
             "value": {"name": "Ann"}, "truncated": False},
            # A deleted entry that held null was found; its value is the stored null.
            {"key": "stored_null", "path": None, "found": True, "created": None,
             "value": None, "truncated": False},
        ],
        "deleted_count": 2,
        "message_type": "key_value",
    }]


NESTED_VALUE = {"name": "Ann", "tags": ["a", "b"], "address": {"city": "Kyiv", "zip": None}}


@pytest.mark.asyncio
async def test_read_message_carries_full_nested_value():
    client = make_client()
    client.read.return_value = read_response({"k": NESTED_VALUE, "long": "ж" * 300})
    node = make_node(
        "read",
        [{"key": "k", "value": "variables.a"}, {"key": "long", "value": "variables.b"}],
        client,
    )
    writer = MagicMock()

    await node.execute(state=make_state({}), writer=writer, execution_order=0, input_={})

    entries = key_value_messages(writer)[0]["entries"]
    assert [(entry["value"], entry["truncated"]) for entry in entries] == [
        (NESTED_VALUE, False),
        ("ж" * 300, False),
    ]


@pytest.mark.asyncio
async def test_write_message_carries_full_nested_value():
    node = make_node("write", [{"key": "k", "value": "variables.profile"}])
    writer = MagicMock()

    await node.execute(
        state=make_state({"profile": NESTED_VALUE}), writer=writer, execution_order=0, input_={}
    )

    [entry] = key_value_messages(writer)[0]["entries"]
    # The value comes from flow state (a DotDict); it must survive the JSON publish as-is.
    assert json.loads(json.dumps(entry["value"])) == NESTED_VALUE
    assert entry["truncated"] is False


@pytest.mark.asyncio
async def test_values_past_message_budget_are_sent_as_truncated_previews(monkeypatch):
    # '"aaaaaaaaaa"' is 12 bytes of JSON: two fit a 30-byte budget, the third does not.
    monkeypatch.setattr(key_value_node, "MESSAGE_VALUE_BUDGET_BYTES", 30)
    client = make_client()
    client.read.return_value = read_response(
        {"k1": "a" * 10, "k2": "a" * 10, "k3": "ж" * 300, "k4": "small", "k5": None}
    )
    node = make_node(
        "read",
        [{"key": f"k{index}", "value": f"variables.v{index}"} for index in range(1, 7)],
        client,
    )
    writer = MagicMock()

    await node.execute(state=make_state({}), writer=writer, execution_order=0, input_={})

    entries = key_value_messages(writer)[0]["entries"]
    assert [(entry["found"], entry["value"], entry["truncated"]) for entry in entries] == [
        (True, "a" * 10, False),
        (True, "a" * 10, False),
        (True, '"' + "ж" * 199, True),
        # Past the budget a value short enough to preview is sent as it is.
        (True, "small", False),
        # A stored null and a missing key carry no value, so they are never truncated.
        (True, None, False),
        (False, None, False),
    ]


@pytest.mark.asyncio
async def test_deleted_values_past_message_budget_are_sent_as_truncated_previews(monkeypatch):
    # '"aaaaaaaaaa"' is 12 bytes of JSON: two fit a 30-byte budget, the third does not.
    monkeypatch.setattr(key_value_node, "MESSAGE_VALUE_BUDGET_BYTES", 30)
    client = make_client()
    client.delete.return_value = delete_response(
        {"k1": "a" * 10, "k2": "a" * 10, "k3": {"text": "ж" * 300}, "k4": "small"}
    )
    node = make_node("delete", [{"key": f"k{index}"} for index in range(1, 6)], client)
    writer = MagicMock()

    await node.execute(state=make_state({}), writer=writer, execution_order=0, input_={})

    [message] = key_value_messages(writer)
    assert message["deleted_count"] == 4
    assert [
        (entry["key"], entry["found"], entry["value"], entry["truncated"])
        for entry in message["entries"]
    ] == [
        ("k1", True, "a" * 10, False),
        ("k2", True, "a" * 10, False),
        ("k3", True, '{"text": "' + "ж" * 190, True),
        ("k4", True, "small", False),
        ("k5", False, None, False),
    ]


def entries_for(mode: str, count: int) -> list[dict]:
    if mode == "delete":
        return [{"key": f"k{index}"} for index in range(count)]
    return [{"key": f"k{index}", "value": f"variables.v{index}"} for index in range(count)]


@pytest.mark.asyncio
async def test_500_entries_are_accepted():
    client = make_client()
    node = make_node("write", entries_for("write", 500), client)

    await run(node, {f"v{index}": index for index in range(500)})

    client.write.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_accepts_canonical_list_indexes():
    client = make_client()
    node = make_node(
        "write",
        [{"key": "first", "value": "variables.tags[0]"}, {"key": "last", "value": "variables.tags[10]"}],
        client,
    )

    output = await run(node, {"tags": list(range(11))})

    assert output == {"first": 0, "last": 10}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
async def test_client_error_is_reported_with_node_context_and_no_key_value_message(mode):
    client = make_client()
    getattr(client, mode).side_effect = ClientValidationError("Key-value table 3 not found.")
    node = make_node(mode, [{"key": "k", "value": "variables.a"}] if mode != "delete" else [{"key": "k"}], client)
    writer = MagicMock()

    with pytest.raises(KeyValueNodeError, match=f"persist_1.*{mode} failed: Key-value table 3 not found"):
        await node.execute(state=make_state({"a": 1}), writer=writer, execution_order=0, input_={})

    assert key_value_messages(writer) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "variables", "message"),
    [
        ("variables.tags.name", {"tags": ["x"]}, "'variables.tags' is a list; use an index like 'variables.tags[0]'"),
        ("variables.tags.append", {"tags": ["x"]}, "'variables.tags' is a list"),
        ("variables.user[0]", {"user": {"id": 1}}, "'variables.user' is an object; use a name like 'variables.user.name'"),
        ("variables.user[0].name", {"user": {"id": 1}}, "'variables.user' is an object"),
        ("variables.missing[0]", {}, "'variables.missing' does not exist"),
        ("variables.a.missing[0]", {"a": {}}, "'variables.a.missing' does not exist"),
        ("variables.tags[3]", {"tags": ["x"]}, "index 3 is out of range for 'variables.tags', which has 1 items"),
        ("variables.tags[5].name", {"tags": ["x"]}, "index 5 is out of range for 'variables.tags'"),
        ("variables.name.first", {"name": "Ann"}, "'variables.name' is a string, so it cannot hold 'first'"),
        ("variables.nothing.first", {"nothing": None}, "'variables.nothing' is null"),
        ("variables.count[0]", {"count": 3}, "'variables.count' is a number, so it has no index [0]"),
    ],
)
async def test_read_rejects_target_that_does_not_fit_the_state(target, variables, message):
    client = make_client()
    client.read.return_value = read_response({"k": 1})
    node = make_node("read", [{"key": "k", "value": target}], client)
    state = make_state(variables)
    writer = MagicMock()
    with pytest.raises(KeyValueNodeError, match=f"persist_1.*{re.escape(message)}"):
        await node.execute(state=state, writer=writer, execution_order=0, input_={})
    assert state["variables"].deep_dump() == variables
    assert key_value_messages(writer) == []


def _read_into(target: str) -> list[dict]:
    return [{"key": "k", "value": target}]


def _write_from(value_path: str) -> list[dict]:
    return [{"key": "k", "value": value_path}]


def _key(key: str) -> list[dict]:
    return [{"value": "variables.out", "key": key}]


REJECTED = [
    # A read target must be a plain path inside the flow state.
    *[
        pytest.param("read", _read_into(target), {"cart": {"total": 3}}, message, id=f"read-target:{target!r}")
        for target, message in [
            ("variables", "whole flow state"),
            ("variables.", "whole flow state"),
            ("profile", "'profile' is not a flow state path"),
            ("", "'' is not a flow state path"),
            ("variables[0]", "is not a flow state path"),
            ("variables.user name", "is not a flow state path"),
            ("variables.a..b", "is not a flow state path"),
            (" variables.a", "is not a flow state path"),
            ("variables.tags[x]", "is not a flow state path"),
            ("variables.tags[01]", "is not a flow state path"),
            ("variables.count|0", "takes no '|default'"),
            ("variables._properties", "'_'"),
            ("variables.user.__dict__", "'_'"),
            ("variables.cart.items", "uses 'items', the name of a built-in method"),
            ("variables.deep_dump.x", "uses 'deep_dump', the name of a built-in method"),
        ]
    ],
    pytest.param(
        "read", [{"key": "k1", "value": "variables.a"}, {"key": "k2", "value": "variables.a"}], {},
        "more than one entry reads into 'variables.a'", id="read-two-keys-into-one-target",
    ),
    pytest.param(
        "read", [{"key": "k1", "value": "variables.a"}, {"key": "k1", "value": "variables.a"}], {},
        "more than one entry reads into 'variables.a'", id="read-duplicate-entry",
    ),
    *[
        pytest.param(
            "read", [{"key": "k1", "value": first}, {"key": "k2", "value": second}], {},
            f"read target '{inner}' is inside read target '{outer}'", id=f"read-nested:{first}+{second}",
        )
        for first, second, inner, outer in [
            ("variables.user", "variables.user.name", "variables.user.name", "variables.user"),
            ("variables.user.name", "variables.user", "variables.user.name", "variables.user"),
            ("variables.users", "variables.users[0]", "variables.users[0]", "variables.users"),
            ("variables.users[0]", "variables.users", "variables.users[0]", "variables.users"),
        ]
    ],
    # A written value must resolve to something storable in the flow state.
    *[
        pytest.param("write", _write_from(value_path), variables, message, id=f"write-value:{value_path!r}")
        for value_path, variables, message in [
            ("variables.user name", {"user": {"id": 1}}, "is not a flow state path"),
            ("variables[0]", {"user": {"id": 1}}, "is not a flow state path"),
            ("variables.a..b|0", {"user": {"id": 1}}, "is not a flow state path"),
            ("variables", {"user": {"id": 1}}, "whole flow state"),
            ("variables.", {"user": {"id": 1}}, "whole flow state"),
            ("variables[", {"user": {"id": 1}}, "whole flow state"),
            ("variables.|0", {"user": {"id": 1}}, "whole flow state"),
            ("variables._properties", {"user": {"_secret": 1}}, re.compile(r"'variables._properties'.*'_'")),
            ("variables.__dict__", {"user": {"_secret": 1}}, re.compile(r"'variables.__dict__'.*'_'")),
            ("variables.user._secret|0", {"user": {"_secret": 1}}, re.compile(r"'variables\.user\._secret\|0'.*'_'")),
            ("variables.cart.items", {"cart": {"total": 3}}, re.compile(r"'variables.cart.items'.*method")),
            ("profile", {"profile": "Ann"}, re.compile(r"'profile'.*variables.user.id")),
            # A missing path would write null over a previously stored value.
            ("variables.profile", {}, "'variables.profile' is missing from the flow state"),
            ("variables.user.middle_name", {"user": {"name": "Ann"}}, "'variables.user.middle_name' is missing from the flow state"),
            ("variables.users[0].middle_name", {"users": [{"name": "Ann"}]}, "'variables.users[0].middle_name' is missing from the flow state"),
            ("variables.user.profile.middle_name", {"user": {}}, "'variables.user.profile.middle_name' is missing from the flow state"),
            ("variables.nothing.first", {"nothing": None}, "'variables.nothing' is null, so it cannot hold 'first'"),
            # getattr on a DotDict finds a dict method before a stored key of the same name, so the
            # resolver cannot read past such a segment: it must raise rather than store null or the
            # default over the real value.
            ("variables.values.total", {"values": {"total": 5}}, "uses 'values', the name of a built-in method"),
            ("variables.items.count", {"items": {"count": 5}}, "uses 'items', the name of a built-in method"),
            ("variables.order.items.count", {"order": {"items": {"count": 5}}}, "uses 'items', the name of a built-in method"),
            ("variables.values.total|0", {"values": {"total": 5}}, "uses 'values', the name of a built-in method"),
            ("variables.values.total|null", {"values": {"total": 5}}, "uses 'values', the name of a built-in method"),
            ("variables.name.upper", {"name": "Ann"}, "'variables.name.upper' resolves to a built-in method"),
            ("variables.tags.count", {"tags": ["x"]}, "'variables.tags.count' resolves to a built-in method"),
        ]
    ],
    *[
        pytest.param(
            "write",
            [{"key": first, "value": "variables.first"}, {"key": second, "value": "variables.second"}],
            {"id": 1, "other_id": "1", "first": 1, "second": 2},
            "more than one entry writes key 'k_1'", id=f"write-same-key:{first}+{second}",
        )
        for first, second in [("k_1", "k_1"), ("k_{variables.id}", "k_1"), ("k_{variables.id}", "k_{ variables.other_id }")]
    ],
    # A key placeholder must resolve to a plain string or number in the flow state.
    *[
        pytest.param("read", _key(key), variables, message, id=f"key:{key!r}:{variables}")
        for key, variables, message in [
            ("profile_{variables.user.id}", {}, "variables.user.id"),
            ("profile_{variables.user_id}", {"user_id": None}, "variables.user_id"),
            ("profile_{user_id}", {"user_id": 42}, re.compile(r"'user_id'.*profile_\{variables\.user\.id\}")),
            ("profile_{ }", {"user_id": 42}, "profile_{variables.user.id}"),
            ("profile_{variables.}", {"user": {"id": 1}}, re.compile(r"'variables.'.*whole flow state")),
            ("k_{variables._properties}", {"user": {"id": 1}}, re.compile(r"'variables._properties'.*'_'")),
            ("cart_{variables.cart.items}", {"cart": {"total": 3}}, re.compile(r"'variables.cart.items'.*method")),
            ("k_{variables.values.id}", {"values": {"id": 1}}, "uses 'values', the name of a built-in method"),
            ("profile_{}", {"x": 1}, "unbalanced placeholder"),
            ("{{variables.x}}", {"x": 1}, "unbalanced placeholder"),
            ("profile_{variables.x", {"x": 1}, "unbalanced placeholder"),
            ("{variables.tags[5]}", {"tags": ["x"]}, "cannot resolve"),
            ("{variables.user[0]}", {"user": {"id": 1}}, "cannot resolve"),
            ("{variables.nothing[0]}", {"nothing": None}, "cannot resolve"),
            ("profile_{variables.user_id}", {"user_id": {"x": 1}}, "string or number"),
            ("profile_{variables.user_id}", {"user_id": [1, 2]}, "string or number"),
        ]
    ],
    *[
        pytest.param(
            mode, [{"key": "user-1"}] if mode == "delete" else [{"key": "user-1", "value": "variables.source"}],
            {"source": 1}, "key 'user-1' resolved to 'user-1', which is not a valid key", id=f"{mode}-invalid-static-key",
        )
        for mode in ("read", "write", "delete")
    ],
    *[
        pytest.param(
            mode, entries_for(mode, 501), {f"v{index}": index for index in range(501)},
            "501 entries; at most 500", id=f"{mode}-too-many-entries",
        )
        for mode in ("read", "write", "delete")
    ],
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "entries", "variables", "message"), REJECTED)
async def test_invalid_entry_is_rejected_before_touching_the_table(mode, entries, variables, message):
    client = make_client()
    node = make_node(mode, entries, client)
    state = make_state(variables)
    writer = MagicMock()

    pattern = message.pattern if isinstance(message, re.Pattern) else re.escape(message)
    with pytest.raises(KeyValueNodeError, match=f"persist_1.*{pattern}"):
        await node.run(state, writer)

    for operation in (client.read, client.write, client.delete):
        operation.assert_not_awaited()
    assert state["variables"].deep_dump() == variables
    assert key_value_messages(writer) == []


@pytest.mark.asyncio
async def test_node_without_table_is_rejected():
    node = make_node("read", _key("k"), table_id=None)

    with pytest.raises(KeyValueNodeError, match="no table"):
        await run(node, {})
