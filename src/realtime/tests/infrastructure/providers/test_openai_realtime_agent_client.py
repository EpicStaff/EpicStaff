"""
Tests for OpenaiRealtimeAgentClient.call_tool() response-continuation behavior.

Regression coverage for: tools/RAG executed correctly on a live voice call but
the agent stayed silent afterward until the caller spoke again. Root cause —
appending a `function_call_output` item does not by itself make OpenAI
generate a new turn; an explicit `response.create` (request_response()) is
required. The Twilio bridge has no client driving that follow-up, so
`call_tool()` must trigger it itself when `is_twilio` is True. The browser
path already gets a follow-up `response.create` from the vendored realtime
client, so it must NOT be duplicated there.
"""
import pytest
from unittest.mock import AsyncMock

from infrastructure.providers.openai.openai_realtime_agent_client import (
    OpenaiRealtimeAgentClient,
)


@pytest.fixture
def client():
    c = OpenaiRealtimeAgentClient(
        api_key="test_key",
        connection_key="conn_1",
        on_server_event=AsyncMock(),
        tool_manager_service=AsyncMock(),
    )
    c.send_server = AsyncMock()
    return c


@pytest.mark.asyncio
async def test_call_tool_sends_function_result(client):
    client.tool_manager_service.execute = AsyncMock(return_value="ok")
    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    sent_events = [c.args[0] for c in client.send_server.await_args_list]
    function_result_events = [
        e for e in sent_events if e.get("type") == "conversation.item.create"
    ]
    assert len(function_result_events) == 1
    assert function_result_events[0]["item"]["call_id"] == "call_1"


@pytest.mark.asyncio
async def test_call_tool_on_twilio_triggers_response_create(client):
    """Twilio bridge has no client to drive a follow-up — call_tool must do it."""
    client.is_twilio = True
    client.tool_manager_service.execute = AsyncMock(return_value="ok")

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    sent_events = [c.args[0] for c in client.send_server.await_args_list]
    response_create_events = [e for e in sent_events if e.get("type") == "response.create"]
    assert len(response_create_events) == 1


@pytest.mark.asyncio
async def test_call_tool_on_browser_does_not_duplicate_response_create(client):
    """Browser session already gets response.create from the vendored client."""
    client.is_twilio = False
    client.tool_manager_service.execute = AsyncMock(return_value="ok")

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    sent_events = [c.args[0] for c in client.send_server.await_args_list]
    response_create_events = [e for e in sent_events if e.get("type") == "response.create"]
    assert len(response_create_events) == 0


@pytest.mark.asyncio
async def test_call_tool_response_create_sent_after_function_result(client):
    """Ordering matters: the tool output must be appended before the response is requested."""
    client.is_twilio = True
    client.tool_manager_service.execute = AsyncMock(return_value="ok")

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    sent_types = [c.args[0].get("type") for c in client.send_server.await_args_list]
    assert sent_types.index("conversation.item.create") < sent_types.index("response.create")


@pytest.mark.asyncio
async def test_request_response_sends_response_create_event(client):
    await client.request_response()
    client.send_server.assert_awaited_once()
    event = client.send_server.await_args[0][0]
    assert event["type"] == "response.create"


def test_base_url_defaults_to_hardcoded_openai_endpoint():
    """EST-3702 regression: no override must reproduce today's exact literal."""
    c = OpenaiRealtimeAgentClient(
        api_key="test_key",
        connection_key="conn_1",
    )
    assert c.base_url == "wss://api.openai.com/v1/realtime"


def test_base_url_uses_custom_override():
    c = OpenaiRealtimeAgentClient(
        api_key="test_key",
        connection_key="conn_1",
        base_url="https://my-proxy.internal",
    )
    assert c.base_url == "wss://my-proxy.internal/v1/realtime"
