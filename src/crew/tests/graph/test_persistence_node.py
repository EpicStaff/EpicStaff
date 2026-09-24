from unittest.mock import AsyncMock, MagicMock

import pytest

from clients.errors import ClientValidationError
from services.graph.exceptions import PersistenceNodeError
from services.graph.nodes.persistence_node import PersistenceNode


def make_node(mode: str, entries: list[dict], client=None, table_id: int | None = 3) -> PersistenceNode:
    return PersistenceNode(
        session_id=7,
        node_name="persist_1",
        stop_event=MagicMock(),
        input_map={},
        output_variable_path="variables.out",
        persistence_table_id=table_id,
        mode=mode,
        entries=entries,
        persistence_client=client or AsyncMock(),
    )


async def run(node: PersistenceNode, input_: dict):
    return await node.execute(state=MagicMock(), writer=MagicMock(), execution_order=0, input_=input_)


@pytest.mark.asyncio
async def test_read_returns_aliases_with_defaults_for_missing_keys():
    client = AsyncMock()
    client.read.return_value = {"profile_42": {"name": "Ann"}, "stored_null": None}
    node = make_node("read", [
        {"alias": "profile", "key": "profile_{user_id}"},
        {"alias": "score", "key": "score_{user_id}", "default": 0},
        {"alias": "nothing", "key": "stored_null", "default": "unused"},
    ], client)

    result = await run(node, {"user_id": 42})

    assert result == {"profile": {"name": "Ann"}, "score": 0, "nothing": None}
    session_id, table_id, keys = client.read.await_args.args
    assert (session_id, table_id) == (7, 3)
    assert sorted(keys) == ["profile_42", "score_42", "stored_null"]


@pytest.mark.asyncio
async def test_write_sends_rendered_keys_and_values():
    client = AsyncMock()
    node = make_node("write", [{"key": "profile_{user_id}", "value": "profile"}], client)

    result = await run(node, {"user_id": 42, "profile": {"name": "Ann"}})

    client.write.assert_awaited_once_with(7, 3, {"profile_42": {"name": "Ann"}})
    assert result == {"profile_42": {"name": "Ann"}}


@pytest.mark.asyncio
async def test_write_duplicate_rendered_keys_last_wins():
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": "first"}, {"key": "k", "value": "second"}], client)
    await run(node, {"first": 1, "second": 2})
    client.write.assert_awaited_once_with(7, 3, {"k": 2})


@pytest.mark.asyncio
async def test_write_with_missing_value_alias_raises():
    client = AsyncMock()
    node = make_node("write", [{"key": "k", "value": "profile"}], client)
    with pytest.raises(PersistenceNodeError, match="profile"):
        await run(node, {})
    client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_sends_rendered_keys():
    client = AsyncMock()
    node = make_node("delete", [{"key": "session_{id}"}, {"key": "static"}], client)
    assert await run(node, {"id": 5}) is None
    client.delete.assert_awaited_once_with(7, 3, ["session_5", "static"])


@pytest.mark.asyncio
async def test_render_key_rejects_unresolved_placeholder():
    node = make_node("read", [{"alias": "a", "key": "profile_{user_id}"}])
    with pytest.raises(PersistenceNodeError, match="user_id"):
        await run(node, {})


@pytest.mark.asyncio
async def test_render_key_rejects_null_placeholder():
    node = make_node("read", [{"alias": "a", "key": "profile_{user_id}"}])
    with pytest.raises(PersistenceNodeError, match="user_id"):
        await run(node, {"user_id": None})


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [{"x": 1}, [1, 2]])
async def test_render_key_rejects_structured_placeholder(value):
    node = make_node("read", [{"alias": "a", "key": "profile_{user_id}"}])
    with pytest.raises(PersistenceNodeError, match="string or number"):
        await run(node, {"user_id": value})


@pytest.mark.asyncio
async def test_render_key_rejects_too_long_key():
    node = make_node("read", [{"alias": "a", "key": "{long}"}])
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
