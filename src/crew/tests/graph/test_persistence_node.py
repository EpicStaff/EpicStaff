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
        output_variable_path="variables.out",
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
async def test_read_returns_aliases_with_defaults_for_missing_keys():
    client = AsyncMock()
    client.read.return_value = {"profile_42": {"name": "Ann"}, "stored_null": None}
    node = make_node("read", [
        {"alias": "profile", "key": "profile_{variables.user_id}"},
        {"alias": "score", "key": "score_{variables.user_id}", "default": 0},
        {"alias": "nothing", "key": "stored_null", "default": "unused"},
    ], client)

    result = await run(node, {"user_id": 42})

    assert result == {"profile": {"name": "Ann"}, "score": 0, "nothing": None}
    session_id, table_id, keys = client.read.await_args.args
    assert (session_id, table_id) == (7, 3)
    assert sorted(keys) == ["profile_42", "score_42", "stored_null"]


@pytest.mark.asyncio
async def test_key_placeholder_resolves_nested_path_and_list_index():
    client = AsyncMock()
    client.read.return_value = {}
    node = make_node(
        "read", [{"alias": "a", "key": "profile_{variables.user.id}_{variables.tags[1]}"}], client
    )

    await run(node, {"user": {"id": 42}, "tags": ["x", "y"]})

    _, _, keys = client.read.await_args.args
    assert keys == ["profile_42_y"]


@pytest.mark.asyncio
async def test_key_placeholder_value_may_contain_braces():
    client = AsyncMock()
    client.read.return_value = {}
    node = make_node("read", [{"alias": "a", "key": "profile_{variables.name}"}], client)

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
    node = make_node("read", [{"alias": "a", "key": "profile_{variables.}"}], client)
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
    node = make_node("read", [{"alias": "a", "key": "profile_{variables.user.id}"}])
    with pytest.raises(PersistenceNodeError, match="variables.user.id"):
        await run(node, {})


@pytest.mark.asyncio
async def test_render_key_rejects_null_placeholder():
    node = make_node("read", [{"alias": "a", "key": "profile_{variables.user_id}"}])
    with pytest.raises(PersistenceNodeError, match="variables.user_id"):
        await run(node, {"user_id": None})


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["profile_{user_id}", "profile_{ }"])
async def test_render_key_rejects_placeholder_outside_variables(key):
    client = AsyncMock()
    node = make_node("read", [{"alias": "a", "key": key}], client)
    with pytest.raises(PersistenceNodeError, match=r"profile_\{variables\.user\.id\}"):
        await run(node, {"user_id": 42})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_render_key_error_names_offending_path():
    node = make_node("read", [{"alias": "a", "key": "profile_{user_id}"}])
    with pytest.raises(PersistenceNodeError) as error:
        await run(node, {"user_id": 42})
    assert "'user_id'" in str(error.value)
    assert "for value" not in str(error.value)


@pytest.mark.asyncio
async def test_render_key_rejects_placeholder_resolving_to_dict_method():
    client = AsyncMock()
    node = make_node("read", [{"alias": "a", "key": "cart_{variables.cart.items}"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*'variables.cart.items'.*method"):
        await run(node, {"cart": {"total": 3}})
    client.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["profile_{}", "{{variables.x}}", "profile_{variables.x"])
async def test_render_key_rejects_leftover_braces(key):
    client = AsyncMock()
    node = make_node("read", [{"alias": "a", "key": key}], client)
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
    node = make_node("read", [{"alias": "a", "key": key}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*cannot resolve"):
        await run(node, variables)
    client.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [{"x": 1}, [1, 2]])
async def test_render_key_rejects_structured_placeholder(value):
    node = make_node("read", [{"alias": "a", "key": "profile_{variables.user_id}"}])
    with pytest.raises(PersistenceNodeError, match="string or number"):
        await run(node, {"user_id": value})


@pytest.mark.asyncio
async def test_render_key_rejects_too_long_key():
    node = make_node("read", [{"alias": "a", "key": "{variables.long}"}])
    with pytest.raises(PersistenceNodeError, match="512"):
        await run(node, {"long": "x" * 513})


@pytest.mark.asyncio
async def test_node_without_table_raises():
    node = make_node("read", [{"alias": "a", "key": "k"}], table_id=None)
    with pytest.raises(PersistenceNodeError, match="no table"):
        await run(node, {})


@pytest.mark.asyncio
async def test_client_errors_are_wrapped_with_node_context():
    client = AsyncMock()
    client.read.side_effect = ClientValidationError("Persistence table 3 not found.")
    node = make_node("read", [{"alias": "a", "key": "k"}], client)
    with pytest.raises(PersistenceNodeError, match="persist_1.*not found"):
        await run(node, {})
