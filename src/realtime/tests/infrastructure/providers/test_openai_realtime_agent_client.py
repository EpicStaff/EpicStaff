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
from tests.conftest import PUBLIC_ERROR_REFERENCE, SECRET_SENTINEL


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


# ---------------------------------------------------------------------------
# call_tool — failing tool never leaks exception text to the provider
# ---------------------------------------------------------------------------


def _function_call_outputs(client) -> list[str]:
    sent_events = [c.args[0] for c in client.send_server.await_args_list]
    return [
        e["item"]["output"] for e in sent_events if e.get("type") == "conversation.item.create"
    ]


@pytest.mark.asyncio
async def test_call_tool_failure_sends_fixed_result_without_exception_text(client):
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    outputs = _function_call_outputs(client)
    assert len(outputs) == 1
    assert outputs[0].startswith("Tool execution failed")
    assert PUBLIC_ERROR_REFERENCE.search(outputs[0])
    for call in client.send_server.await_args_list:
        assert SECRET_SENTINEL not in str(call.args[0])


@pytest.mark.asyncio
async def test_call_tool_failure_logs_detail_under_the_sent_correlation_id(
    client, captured_log_messages
):
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    correlation_id = PUBLIC_ERROR_REFERENCE.search(_function_call_outputs(client)[0]).group(1)
    matching_logs = [message for message in captured_log_messages if correlation_id in message]
    assert len(matching_logs) == 1
    assert SECRET_SENTINEL in matching_logs[0]


@pytest.mark.asyncio
async def test_call_tool_failure_on_twilio_still_requests_a_response(client):
    """Without the follow-up response.create the model stays silent after a failed tool."""
    client.is_twilio = True
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("call_1", "search_tool", {"query": "hi"})

    sent_types = [c.args[0].get("type") for c in client.send_server.await_args_list]
    assert sent_types == ["conversation.item.create", "response.create"]


@pytest.mark.asyncio
async def test_request_response_sends_response_create_event(client):
    await client.request_response()
    client.send_server.assert_awaited_once()
    event = client.send_server.await_args[0][0]
    assert event["type"] == "response.create"


def test_blank_voice_falls_back_to_alloy():
    """A falsy `voice` (empty string, as allow_blank serializers permit) must
    not reach OpenAI unguarded -- it errors/garbles audio there."""
    c = OpenaiRealtimeAgentClient(
        api_key="test_key",
        connection_key="conn_1",
        voice="",
    )
    assert c.voice == "alloy"


def test_omitted_voice_falls_back_to_alloy():
    c = OpenaiRealtimeAgentClient(
        api_key="test_key",
        connection_key="conn_1",
    )
    assert c.voice == "alloy"


def test_explicit_voice_is_preserved():
    c = OpenaiRealtimeAgentClient(
        api_key="test_key",
        connection_key="conn_1",
        voice="verse",
    )
    assert c.voice == "verse"


@pytest.mark.asyncio
async def test_update_session_blank_voice_override_falls_back_to_instance_voice(client):
    """`config.get("voice", self.voice)` does not fall back on an explicit
    empty string -- only `.get(key, default) or self.voice` does."""
    client.voice = "verse"

    await client.update_session(config={"voice": ""})

    event = client.send_server.await_args[0][0]
    assert event["session"]["audio"]["output"]["voice"] == "verse"


@pytest.mark.asyncio
async def test_update_session_missing_voice_key_falls_back_to_instance_voice(client):
    client.voice = "verse"

    await client.update_session(config={})

    event = client.send_server.await_args[0][0]
    assert event["session"]["audio"]["output"]["voice"] == "verse"


@pytest.mark.asyncio
async def test_update_session_explicit_voice_override_is_used(client):
    client.voice = "alloy"

    await client.update_session(config={"voice": "coral"})

    event = client.send_server.await_args[0][0]
    assert event["session"]["audio"]["output"]["voice"] == "coral"


def test_base_url_defaults_to_hardcoded_openai_endpoint():
    """No override must reproduce today's exact literal."""
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
