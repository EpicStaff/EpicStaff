import json
import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from dotdict import DotDict

from clients.errors import ClientValidationError
from services.graph.exceptions import PersistenceNodeError
from services.graph.nodes import persistence_node
from services.graph.nodes.persistence_node import PersistenceNode

TABLE_NAME = "Customers"


def read_response(values: dict) -> dict:
    return {"values": values, "table_name": TABLE_NAME}


def make_client(created: list[str] | None = None, deleted: int = 0) -> AsyncMock:
    """A client whose calls return Django's response shapes."""
    client = AsyncMock()
    client.read.return_value = read_response({})
    client.write.return_value = {"written": 0, "created": created or [], "table_name": TABLE_NAME}
    client.delete.return_value = {"deleted": deleted, "table_name": TABLE_NAME}
    return client


def persistence_messages(writer: MagicMock) -> list[dict]:
    return [
        call.args[0].message_data
        for call in writer.call_args_list
        if call.args[0].message_data.get("message_type") == "persistence"
    ]


def make_node(
    mode: str,
    entries: list[dict],
    client=None,
    table_id: int | None = 3,
) -> PersistenceNode:
    return PersistenceNode(
        session_id=7,
        node_name="persist_1",
        stop_event=MagicMock(),
        persistence_table_id=table_id,
        mode=mode,
        entries=entries,
        persistence_client=client or make_client(),
    )


def make_state(variables: dict) -> dict:
    return {"state_history": [], "variables": DotDict(variables), "system_variables": {}}


async def run(node: PersistenceNode, variables: dict):
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
@pytest.mark.parametrize(
    ("target", "message"),
    [
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
    ],
)
async def test_read_rejects_bad_target_path_before_reading(target, message):
    client = make_client()
    node = make_node("read", [{"key": "k", "value": target}], client)
    with pytest.raises(PersistenceNodeError, match=f"persist_1.*{re.escape(message)}"):
        await run(node, {"cart": {"total": 3}})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entries",
    [
        [{"key": "k1", "value": "variables.a"}, {"key": "k2", "value": "variables.a"}],
        [{"key": "k1", "value": "variables.a"}, {"key": "k1", "value": "variables.a"}],
    ],
)
async def test_read_rejects_two_entries_with_the_same_target_before_reading(entries):
    client = make_client()
    node = make_node("read", entries, client)
    writer = MagicMock()

    with pytest.raises(
        PersistenceNodeError, match="persist_1.*more than one entry reads into 'variables.a'"
    ):
        await node.execute(state=make_state({}), writer=writer, execution_order=0, input_={})

    client.read.assert_not_awaited()
    assert persistence_messages(writer) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first", "second", "inner", "outer"),
    [
        ("variables.user", "variables.user.name", "variables.user.name", "variables.user"),
        ("variables.user.name", "variables.user", "variables.user.name", "variables.user"),
        ("variables.users", "variables.users[0]", "variables.users[0]", "variables.users"),
        ("variables.users[0]", "variables.users", "variables.users[0]", "variables.users"),
    ],
)
async def test_read_rejects_a_target_nested_in_another_before_reading(first, second, inner, outer):
    client = make_client()
    node = make_node(
        "read", [{"key": "k1", "value": first}, {"key": "k2", "value": second}], client
    )

    with pytest.raises(
        PersistenceNodeError,
        match=re.escape(f"read target '{inner}' is inside read target '{outer}'"),
    ):
        await run(node, {})

    client.read.assert_not_awaited()


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
    with pytest.raises(PersistenceNodeError, match=f"persist_1.*{re.escape(message)}"):
        await node.execute(state=state, writer=writer, execution_order=0, input_={})
    assert state["variables"].deep_dump() == variables
    assert persistence_messages(writer) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value_path", ["variables.user name", "variables[0]", "variables.a..b|0"])
async def test_write_value_that_is_not_a_canonical_state_path_raises(value_path):
    client = make_client()
    node = make_node("write", [{"key": "k", "value": value_path}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*is not a flow state path"):
        await run(node, {"user": {"id": 1}})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_key_placeholder_resolves_nested_path_and_list_index():
    client = make_client()
    client.read.return_value = read_response({})
    node = make_node(
        "read", [{"value": "variables.out", "key": "profile_{variables.user.id}_{variables.tags[1]}"}], client
    )

    await run(node, {"user": {"id": 42}, "tags": ["x", "y"]})

    _, _, keys = client.read.await_args.args
    assert keys == ["profile_42_y"]


@pytest.mark.asyncio
async def test_key_placeholder_ignores_surrounding_spaces():
    client = make_client()
    client.read.return_value = read_response({})
    node = make_node("read", [{"value": "variables.out", "key": "p_{ variables.user.id }"}], client)

    await run(node, {"user": {"id": 42}})

    _, _, keys = client.read.await_args.args
    assert keys == ["p_42"]


@pytest.mark.asyncio
async def test_key_placeholder_value_with_braces_is_rejected():
    client = make_client()
    node = make_node("read", [{"value": "variables.out", "key": "profile_{variables.name}"}], client)

    with pytest.raises(PersistenceNodeError) as error:
        await run(node, {"name": "a{b}"})

    assert str(error.value) == (
        "Persistence node 'persist_1': key 'profile_{variables.name}' resolved to "
        f"'profile_a{{b}}', which is not a valid key: {persistence_node.KEY_RULE}."
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
async def test_write_value_null_default_raises():
    client = make_client()
    node = make_node("write", [{"key": "count", "value": "variables.count|null"}], client)
    with pytest.raises(PersistenceNodeError, match="variables.count"):
        await run(node, {})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value_path", ["variables", "variables.", "variables[", "variables.|0"])
async def test_write_value_naming_whole_state_raises(value_path):
    client = make_client()
    node = make_node("write", [{"key": "k", "value": value_path}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*whole flow state"):
        await run(node, {"user": {"id": 1}})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_render_key_rejects_placeholder_naming_whole_state():
    client = make_client()
    node = make_node("read", [{"value": "variables.out", "key": "profile_{variables.}"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables.'.*whole flow state"):
        await run(node, {"user": {"id": 1}})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_value_resolving_to_dict_method_raises():
    client = make_client()
    node = make_node("write", [{"key": "k", "value": "variables.cart.items"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables.cart.items'.*method"):
        await run(node, {"cart": {"total": 3}})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value_path", ["variables._properties", "variables.__dict__", "variables.user._secret|0"]
)
async def test_write_value_naming_internal_attribute_raises(value_path):
    client = make_client()
    node = make_node("write", [{"key": "k", "value": value_path}], client)
    with pytest.raises(PersistenceNodeError, match=f"persist_1.*'{re.escape(value_path)}'.*'_'"):
        await run(node, {"user": {"_secret": 1}})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_render_key_rejects_placeholder_naming_internal_attribute():
    client = make_client()
    node = make_node("read", [{"value": "variables.out", "key": "k_{variables._properties}"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables._properties'.*'_'"):
        await run(node, {"user": {"id": 1}})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "keys",
    [
        ("k_1", "k_1"),
        ("k_{variables.id}", "k_1"),
        ("k_{variables.id}", "k_{ variables.other_id }"),
    ],
)
async def test_write_rejects_entries_rendering_to_the_same_key(keys):
    client = make_client()
    node = make_node(
        "write",
        [{"key": keys[0], "value": "variables.first"}, {"key": keys[1], "value": "variables.second"}],
        client,
    )
    with pytest.raises(PersistenceNodeError, match="persist_1': more than one entry writes key 'k_1'"):
        await run(node, {"id": 1, "other_id": "1", "first": 1, "second": 2})
    client.write.assert_not_awaited()


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
async def test_write_with_missing_value_path_raises():
    client = make_client()
    node = make_node("write", [{"key": "k", "value": "variables.profile"}], client)
    with pytest.raises(PersistenceNodeError, match="variables.profile"):
        await run(node, {})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_with_null_value_raises():
    client = make_client()
    node = make_node("write", [{"key": "k", "value": "variables.profile"}], client)
    with pytest.raises(PersistenceNodeError, match="null"):
        await run(node, {"profile": None})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_value_outside_variables_raises():
    client = make_client()
    node = make_node("write", [{"key": "k", "value": "profile"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'profile'.*variables.user.id"):
        await run(node, {"profile": "Ann"})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_raises_when_value_path_does_not_resolve():
    """Regression: the resolver returns None (logging only a warning) for a path that is
    not in the state, so the node's own null check is what stops it writing a null over a
    previously stored value. Goes through the real `run()` path."""
    client = make_client()
    node = make_node("write", [{"key": "k", "value": "variables.profile"}], client)

    with pytest.raises(PersistenceNodeError, match="variables.profile"):
        await node.run(make_state({}), MagicMock())

    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_sends_rendered_keys():
    client = make_client()
    node = make_node("delete", [{"key": "session_{variables.id}"}, {"key": "static"}], client)
    assert await run(node, {"id": 5}) is None
    client.delete.assert_awaited_once_with(7, 3, ["session_5", "static"])


@pytest.mark.asyncio
async def test_render_key_rejects_unresolved_placeholder():
    node = make_node("read", [{"value": "variables.out", "key": "profile_{variables.user.id}"}])
    with pytest.raises(PersistenceNodeError, match="variables.user.id"):
        await run(node, {})


@pytest.mark.asyncio
async def test_render_key_rejects_null_placeholder():
    node = make_node("read", [{"value": "variables.out", "key": "profile_{variables.user_id}"}])
    with pytest.raises(PersistenceNodeError, match="variables.user_id"):
        await run(node, {"user_id": None})


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["profile_{user_id}", "profile_{ }"])
async def test_render_key_rejects_placeholder_outside_variables(key):
    client = make_client()
    node = make_node("read", [{"value": "variables.out", "key": key}], client)
    with pytest.raises(PersistenceNodeError, match=r"profile_\{variables\.user\.id\}"):
        await run(node, {"user_id": 42})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_render_key_error_names_offending_path():
    node = make_node("read", [{"value": "variables.out", "key": "profile_{user_id}"}])
    with pytest.raises(PersistenceNodeError) as error:
        await run(node, {"user_id": 42})
    assert "'user_id'" in str(error.value)
    assert "for value" not in str(error.value)


@pytest.mark.asyncio
async def test_render_key_rejects_placeholder_resolving_to_dict_method():
    client = make_client()
    node = make_node("read", [{"value": "variables.out", "key": "cart_{variables.cart.items}"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables.cart.items'.*method"):
        await run(node, {"cart": {"total": 3}})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["profile_{}", "{{variables.x}}", "profile_{variables.x"])
async def test_render_key_rejects_leftover_braces(key):
    client = make_client()
    node = make_node("read", [{"value": "variables.out", "key": key}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*unbalanced placeholder"):
        await run(node, {"x": 1})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "variables"),
    [
        ("{variables.tags[5]}", {"tags": ["x"]}),
        ("{variables.user[0]}", {"user": {"id": 1}}),
        ("{variables.nothing[0]}", {"nothing": None}),
    ],
)
async def test_render_key_rejects_bad_list_index(key, variables):
    client = make_client()
    node = make_node("read", [{"value": "variables.out", "key": key}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*cannot resolve"):
        await run(node, variables)
    client.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [{"x": 1}, [1, 2]])
async def test_render_key_rejects_structured_placeholder(value):
    node = make_node("read", [{"value": "variables.out", "key": "profile_{variables.user_id}"}])
    with pytest.raises(PersistenceNodeError, match="string or number"):
        await run(node, {"user_id": value})


@pytest.mark.asyncio
async def test_render_key_rejects_too_long_key():
    node = make_node("read", [{"value": "variables.out", "key": "{variables.long}"}])
    with pytest.raises(PersistenceNodeError) as error:
        await run(node, {"long": "x" * 513})
    assert str(error.value) == (
        "Persistence node 'persist_1': key '{variables.long}' resolved to "
        f"'{'x' * 100}…', which is not a valid key: use only letters, digits and _, "
        "don't start with a digit, and keep it to at most 512 characters."
    )


# Keep identical to the resolved-key parity table in Django's
# tests/services_tests/test_persistence_table_service.py.
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

    with pytest.raises(PersistenceNodeError) as error:
        await run(node, {"key": resolved, "source": 1})

    shown = resolved if len(resolved) <= 100 else f"{resolved[:100]}…"
    assert str(error.value) == (
        f"Persistence node 'persist_1': key '{{variables.key}}' resolved to {shown!r}, "
        f"which is not a valid key: {persistence_node.KEY_RULE}."
    )
    getattr(client, mode).assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
async def test_saved_static_key_with_invalid_characters_is_rejected(mode):
    client = make_client()
    node = make_node(mode, one_entry(mode, "user-1"), client)

    with pytest.raises(PersistenceNodeError, match="key 'user-1' resolved to 'user-1', which is not a valid key"):
        await run(node, {"source": 1})

    getattr(client, mode).assert_not_awaited()


@pytest.mark.asyncio
async def test_node_without_table_raises():
    node = make_node("read", [{"value": "variables.out", "key": "k"}], table_id=None)
    with pytest.raises(PersistenceNodeError, match="no table"):
        await run(node, {})


@pytest.mark.asyncio
async def test_client_errors_are_wrapped_with_node_context():
    client = make_client()
    client.read.side_effect = ClientValidationError("Persistence table 3 not found.")
    node = make_node("read", [{"value": "variables.out", "key": "k"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*not found"):
        await run(node, {})


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

    assert persistence_messages(writer) == [{
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
        "message_type": "persistence",
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
    [message] = persistence_messages(writer)
    assert message["mode"] == "write"
    assert message["table_name"] == "Customers"
    assert message["entries"] == [
        {"key": "new", "path": "variables.a", "found": None, "created": True,
         "value": "Ann", "truncated": False},
        {"key": "old_1", "path": "variables.missing|fallback", "found": None, "created": False,
         "value": "fallback", "truncated": False},
    ]


@pytest.mark.asyncio
async def test_delete_emits_message_with_deleted_count_and_requested_keys():
    client = make_client(deleted=1)
    node = make_node("delete", [{"key": "b"}, {"key": "a"}, {"key": "b"}], client)
    writer = MagicMock()

    await node.execute(state=make_state({}), writer=writer, execution_order=0, input_={})

    [message] = persistence_messages(writer)
    assert message["mode"] == "delete"
    assert message["deleted_count"] == 1
    assert [entry["key"] for entry in message["entries"]] == ["a", "b"]
    assert all(entry["path"] is None for entry in message["entries"])
    assert all(entry["value"] is None for entry in message["entries"])
    assert not any(entry["truncated"] for entry in message["entries"])


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

    entries = persistence_messages(writer)[0]["entries"]
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

    [entry] = persistence_messages(writer)[0]["entries"]
    # The value comes from flow state (a DotDict); it must survive the JSON publish as-is.
    assert json.loads(json.dumps(entry["value"])) == NESTED_VALUE
    assert entry["truncated"] is False


@pytest.mark.asyncio
async def test_values_past_message_budget_are_sent_as_truncated_previews(monkeypatch):
    # '"aaaaaaaaaa"' is 12 bytes of JSON: two fit a 30-byte budget, the third does not.
    monkeypatch.setattr(persistence_node, "MESSAGE_VALUE_BUDGET_BYTES", 30)
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

    entries = persistence_messages(writer)[0]["entries"]
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


def entries_for(mode: str, count: int) -> list[dict]:
    if mode == "delete":
        return [{"key": f"k{index}"} for index in range(count)]
    return [{"key": f"k{index}", "value": f"variables.v{index}"} for index in range(count)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
async def test_more_than_500_entries_are_rejected_before_calling_the_table(mode):
    client = make_client()
    node = make_node(mode, entries_for(mode, 501), client)

    with pytest.raises(PersistenceNodeError, match="persist_1.*501 entries; at most 500"):
        await run(node, {f"v{index}": index for index in range(501)})

    client.read.assert_not_awaited()
    client.write.assert_not_awaited()
    client.delete.assert_not_awaited()


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
async def test_client_error_emits_no_persistence_message(mode):
    client = make_client()
    getattr(client, mode).side_effect = ClientValidationError("Persistence table 3 not found.")
    node = make_node(mode, [{"key": "k", "value": "variables.a"}] if mode != "delete" else [{"key": "k"}], client)
    writer = MagicMock()

    with pytest.raises(PersistenceNodeError):
        await node.execute(state=make_state({"a": 1}), writer=writer, execution_order=0, input_={})

    assert persistence_messages(writer) == []
