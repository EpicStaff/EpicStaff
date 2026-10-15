"""
ElevenLabsRealtimeAgentClient.call_tool(): a failing tool sends a fixed result.

The tool result goes to ElevenLabs (`client_tool_result`) and to the browser
(`conversation.item.created`), so neither may carry the exception text.
"""
from unittest.mock import AsyncMock

import pytest

from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import (
    ElevenLabsRealtimeAgentClient,
)
from tests.conftest import PUBLIC_ERROR_REFERENCE, SECRET_SENTINEL


@pytest.fixture
def client():
    c = ElevenLabsRealtimeAgentClient(
        api_key="test_key",
        connection_key="conn_1",
        on_server_event=AsyncMock(),
        tool_manager_service=AsyncMock(),
    )
    c.send_server = AsyncMock()
    c.send_client = AsyncMock()
    return c


def _provider_tool_results(client) -> list[str]:
    sent_events = [c.args[0] for c in client.send_server.await_args_list]
    return [e["result"] for e in sent_events if e.get("type") == "client_tool_result"]


@pytest.mark.asyncio
async def test_call_tool_sends_tool_result(client):
    client.tool_manager_service.execute = AsyncMock(return_value="ok")

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    assert _provider_tool_results(client) == ["ok"]


@pytest.mark.asyncio
async def test_call_tool_failure_sends_fixed_result_without_exception_text(client):
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    results = _provider_tool_results(client)
    assert len(results) == 1
    assert results[0].startswith("Tool execution failed")
    assert PUBLIC_ERROR_REFERENCE.search(results[0])
    for call in client.send_server.await_args_list + client.send_client.await_args_list:
        assert SECRET_SENTINEL not in str(call.args[0])


@pytest.mark.asyncio
async def test_call_tool_failure_shows_the_same_reference_to_the_browser(client):
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    correlation_id = PUBLIC_ERROR_REFERENCE.search(_provider_tool_results(client)[0]).group(1)
    browser_outputs = [
        c.args[0]["item"]["output"]
        for c in client.send_client.await_args_list
        if c.args[0].get("type") == "conversation.item.created"
    ]
    assert len(browser_outputs) == 1
    assert correlation_id in browser_outputs[0]


@pytest.mark.asyncio
async def test_call_tool_failure_logs_detail_under_the_sent_correlation_id(
    client, captured_log_messages
):
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    correlation_id = PUBLIC_ERROR_REFERENCE.search(_provider_tool_results(client)[0]).group(1)
    matching_logs = [message for message in captured_log_messages if correlation_id in message]
    assert len(matching_logs) == 1
    assert SECRET_SENTINEL in matching_logs[0]
