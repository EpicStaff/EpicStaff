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
from tests.conftest import (
    INJECTED_TOOL_RESULT,
    PUBLIC_ERROR_REFERENCE,
    SECRET_SENTINEL,
    unwrap_tool_result,
)


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


def _browser_tool_outputs(client) -> list[str]:
    sent_events = [c.args[0] for c in client.send_client.await_args_list]
    return [e["item"]["output"] for e in sent_events if e.get("type") == "conversation.item.created"]


@pytest.mark.asyncio
async def test_call_tool_sends_tool_result(client):
    client.tool_manager_service.execute = AsyncMock(return_value="ok")

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    (result,) = _provider_tool_results(client)
    assert unwrap_tool_result(result) == "ok"


@pytest.mark.asyncio
async def test_tool_result_reaches_elevenlabs_enveloped_and_the_browser_plain(client):
    client.tool_manager_service.execute = AsyncMock(return_value=INJECTED_TOOL_RESULT)

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    (result,) = _provider_tool_results(client)
    assert unwrap_tool_result(result) == INJECTED_TOOL_RESULT
    assert _browser_tool_outputs(client) == [INJECTED_TOOL_RESULT]


@pytest.mark.asyncio
async def test_tool_failure_reaches_provider_and_browser_without_the_exception_text(client, captured_log_messages):
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    (enveloped,) = _provider_tool_results(client)
    result = unwrap_tool_result(enveloped)
    assert result.startswith("Tool execution failed")
    for call in client.send_server.await_args_list + client.send_client.await_args_list:
        assert SECRET_SENTINEL not in str(call.args[0])
    # The browser shows the same reference, and support finds the detail under it in the logs.
    correlation_id = PUBLIC_ERROR_REFERENCE.search(result).group(1)
    (browser_output,) = _browser_tool_outputs(client)
    assert correlation_id in browser_output
    (log,) = [message for message in captured_log_messages if correlation_id in message]
    assert SECRET_SENTINEL in log
