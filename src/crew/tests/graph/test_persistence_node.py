import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from dotdict import DotDict

from clients.errors import ClientValidationError
from services.graph.exceptions import PersistenceNodeError
from services.graph.nodes.persistence_node import PersistenceNode


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
        persistence_client=client or AsyncMock(),
    )


def make_state(variables: dict) -> dict:
    return {"state_history": [], "variables": DotDict(variables), "system_variables": {}}


async def run(node: PersistenceNode, variables: dict):
    return await node.execute(
        state=make_state(variables), writer=MagicMock(), execution_order=0, input_={}
    )


@pytest.mark.asyncio
async def test_read_writes_stored_values_to_target_paths_and_none_for_missing_keys():
    client = AsyncMock()
    client.read.return_value = {"profile_42": {"name": "Ann"}, "stored_null": None}
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
    client = AsyncMock()
    client.read.return_value = {"k": "Ann"}
    node = make_node("read", [{"key": "k", "value": "variables.users[1].name"}], client)
    state = make_state({"users": [{"name": "a"}, {"name": "b"}]})

    await node.execute(state=state, writer=MagicMock(), execution_order=0, input_={})

    assert state["variables"].deep_dump() == {"users": [{"name": "a"}, {"name": "Ann"}]}


@pytest.mark.asyncio
async def test_read_through_run_writes_only_target_paths():
    client = AsyncMock()
    client.read.return_value = {"k": 1}
    node = make_node("read", [{"key": "k", "value": "variables.count"}], client)
    state = make_state({"out": "untouched"})

    await node.run(state, MagicMock())

    assert node.output_variable_path is None
    assert state["variables"].deep_dump() == {"out": "untouched", "count": 1}


@pytest.mark.asyncio
async def test_read_replaces_existing_object_instead_of_merging():
    client = AsyncMock()
    client.read.return_value = {"k": {"name": "Ann"}}
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
        ("variables.count|0", "takes no '|default'"),
        ("variables._properties", "'_'"),
        ("variables.user.__dict__", "'_'"),
        ("variables.cart.items", "uses 'items', the name of a built-in method"),
        ("variables.deep_dump.x", "uses 'deep_dump', the name of a built-in method"),
    ],
)
async def test_read_rejects_bad_target_path_before_reading(target, message):
    client = AsyncMock()
    node = make_node("read", [{"key": "k", "value": target}], client)
    with pytest.raises(PersistenceNodeError, match=f"persist_1.*{re.escape(message)}"):
        await run(node, {"cart": {"total": 3}})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_rejects_duplicate_targets_before_reading():
    client = AsyncMock()
    node = make_node(
        "read",
        [{"key": "k1", "value": "variables.a"}, {"key": "k2", "value": "variables.a"}],
        client,
    )
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables.a' receives more than one"):
        await run(node, {})
    client.read.assert_not_awaited()


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
    client = AsyncMock()
    client.read.return_value = {"k": 1}
    node = make_node("read", [{"key": "k", "value": target}], client)
    state = make_state(variables)
    with pytest.raises(PersistenceNodeError, match=f"persist_1.*{re.escape(message)}"):
        await node.execute(state=state, writer=MagicMock(), execution_order=0, input_={})
    assert state["variables"].deep_dump() == variables


@pytest.mark.asyncio
@pytest.mark.parametrize("value_path", ["variables.user name", "variables[0]", "variables.a..b|0"])
async def test_write_value_that_is_not_a_canonical_state_path_raises(value_path):
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": value_path}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*is not a flow state path"):
        await run(node, {"user": {"id": 1}})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_key_placeholder_resolves_nested_path_and_list_index():
    client = AsyncMock()
    client.read.return_value = {}
    node = make_node(
        "read", [{"value": "variables.out", "key": "profile_{variables.user.id}_{variables.tags[1]}"}], client
    )

    await run(node, {"user": {"id": 42}, "tags": ["x", "y"]})

    _, _, keys = client.read.await_args.args
    assert keys == ["profile_42_y"]


@pytest.mark.asyncio
async def test_key_placeholder_ignores_surrounding_spaces():
    client = AsyncMock()
    client.read.return_value = {}
    node = make_node("read", [{"value": "variables.out", "key": "p_{ variables.user.id }"}], client)

    await run(node, {"user": {"id": 42}})

    _, _, keys = client.read.await_args.args
    assert keys == ["p_42"]


@pytest.mark.asyncio
async def test_key_placeholder_value_may_contain_braces():
    client = AsyncMock()
    client.read.return_value = {}
    node = make_node("read", [{"value": "variables.out", "key": "profile_{variables.name}"}], client)

    await run(node, {"name": "a{b}"})

    _, _, keys = client.read.await_args.args
    assert keys == ["profile_a{b}"]


@pytest.mark.asyncio
async def test_write_sends_rendered_keys_and_state_path_values():
    client = AsyncMock()
    node = make_node(
        "write", [{"key": "profile_{variables.user.id}", "value": "variables.user.profile"}], client
    )

    result = await run(node, {"user": {"id": 42, "profile": {"name": "Ann"}}})

    client.write.assert_awaited_once_with(7, 3, {"profile_42": {"name": "Ann"}})
    assert result == {"profile_42": {"name": "Ann"}}


@pytest.mark.asyncio
async def test_write_value_default_applies_when_path_is_missing():
    client = AsyncMock()
    node = make_node("write", [{"key": "count", "value": "variables.count|0"}], client)

    await run(node, {})

    client.write.assert_awaited_once_with(7, 3, {"count": 0})


@pytest.mark.asyncio
async def test_write_value_null_default_raises():
    client = AsyncMock()
    node = make_node("write", [{"key": "count", "value": "variables.count|null"}], client)
    with pytest.raises(PersistenceNodeError, match="variables.count"):
        await run(node, {})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value_path", ["variables", "variables.", "variables[", "variables.|0"])
async def test_write_value_naming_whole_state_raises(value_path):
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": value_path}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*whole flow state"):
        await run(node, {"user": {"id": 1}})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_render_key_rejects_placeholder_naming_whole_state():
    client = AsyncMock()
    node = make_node("read", [{"value": "variables.out", "key": "profile_{variables.}"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables.'.*whole flow state"):
        await run(node, {"user": {"id": 1}})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_value_resolving_to_dict_method_raises():
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": "variables.cart.items"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables.cart.items'.*method"):
        await run(node, {"cart": {"total": 3}})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value_path", ["variables._properties", "variables.__dict__", "variables.user._secret|0"]
)
async def test_write_value_naming_internal_attribute_raises(value_path):
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": value_path}], client)
    with pytest.raises(PersistenceNodeError, match=f"persist_1.*'{re.escape(value_path)}'.*'_'"):
        await run(node, {"user": {"_secret": 1}})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_render_key_rejects_placeholder_naming_internal_attribute():
    client = AsyncMock()
    node = make_node("read", [{"value": "variables.out", "key": "k_{variables._properties}"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables._properties'.*'_'"):
        await run(node, {"user": {"id": 1}})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_duplicate_rendered_keys_last_wins():
    client = AsyncMock()
    node = make_node(
        "write",
        [{"key": "k", "value": "variables.first"}, {"key": "k", "value": "variables.second"}],
        client,
    )
    await run(node, {"first": 1, "second": 2})
    client.write.assert_awaited_once_with(7, 3, {"k": 2})


@pytest.mark.asyncio
async def test_write_with_missing_value_path_raises():
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": "variables.profile"}], client)
    with pytest.raises(PersistenceNodeError, match="variables.profile"):
        await run(node, {})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_with_null_value_raises():
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": "variables.profile"}], client)
    with pytest.raises(PersistenceNodeError, match="null"):
        await run(node, {"profile": None})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_value_outside_variables_raises():
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": "profile"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'profile'.*variables.user.id"):
        await run(node, {"profile": "Ann"})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_raises_when_value_path_does_not_resolve():
    """Regression: the resolver returns None (logging only a warning) for a path that is
    not in the state, so the node's own null check is what stops it writing a null over a
    previously stored value. Goes through the real `run()` path."""
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": "variables.profile"}], client)

    with pytest.raises(PersistenceNodeError, match="variables.profile"):
        await node.run(make_state({}), MagicMock())

    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_sends_rendered_keys():
    client = AsyncMock()
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
    client = AsyncMock()
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
    client = AsyncMock()
    node = make_node("read", [{"value": "variables.out", "key": "cart_{variables.cart.items}"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables.cart.items'.*method"):
        await run(node, {"cart": {"total": 3}})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["profile_{}", "{{variables.x}}", "profile_{variables.x"])
async def test_render_key_rejects_leftover_braces(key):
    client = AsyncMock()
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
    client = AsyncMock()
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
    with pytest.raises(PersistenceNodeError, match="512"):
        await run(node, {"long": "x" * 513})


@pytest.mark.asyncio
async def test_node_without_table_raises():
    node = make_node("read", [{"value": "variables.out", "key": "k"}], table_id=None)
    with pytest.raises(PersistenceNodeError, match="no table"):
        await run(node, {})


@pytest.mark.asyncio
async def test_client_errors_are_wrapped_with_node_context():
    client = AsyncMock()
    client.read.side_effect = ClientValidationError("Persistence table 3 not found.")
    node = make_node("read", [{"value": "variables.out", "key": "k"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*not found"):
        await run(node, {})
