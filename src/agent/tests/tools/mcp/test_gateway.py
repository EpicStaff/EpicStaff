"""
Tests for McpToolGateway.

Mocks the FastMCPClientFactory and fastmcp Client to avoid real network I/O.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from app.exceptions import McpToolError
from app.tools.mcp import gateway as gateway_module
from app.tools.mcp.client_factory import FastMCPClientFactory
from app.tools.mcp.gateway import McpToolGateway
from fastmcp import Client, Context, FastMCP
from mcp import McpError
from mcp.types import INTERNAL_ERROR, ErrorData
from shared.models.tools import McpToolData

# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


def _mcp_data(tool_name: str = "search") -> McpToolData:
    return McpToolData(transport="http://localhost/sse", tool_name=tool_name)


@dataclass
class FakeTool:
    name: str
    description: str = "A fake tool."
    inputSchema: dict = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class FakeCallResult:
    is_error: bool = False
    structured_content: dict | None = None
    content: list = field(default_factory=list)
    data: object = None


@dataclass
class FakeTextContent:
    text: str


@dataclass
class FakeImageContent:
    data: str
    type: str = "image"
    mimeType: str = "image/png"


@dataclass
class FakeResourceLink:
    uri: str
    type: str = "resource_link"


def _make_client(list_tools_result=None, call_tool_result=None, raise_on_enter=None):
    """Build a fake fastmcp Client that supports 'async with'."""
    client = MagicMock()

    if raise_on_enter:

        @asynccontextmanager
        async def _ctx():
            raise raise_on_enter
            yield  # noqa: unreachable

        client.__aenter__ = lambda self: _ctx().__aenter__()
        client.__aexit__ = AsyncMock(return_value=False)
    else:
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

    if list_tools_result is not None:
        client.list_tools = AsyncMock(return_value=list_tools_result)

    if call_tool_result is not None:
        client.call_tool = AsyncMock(return_value=call_tool_result)

    return client


def _factory(client) -> FastMCPClientFactory:
    factory = MagicMock(spec=FastMCPClientFactory)
    factory.create.return_value = client
    return factory


_IN_FLIGHT_REQUEST_ID = 1


def _sdk_read_timeout() -> McpError:
    """The error mcp's send_request raises when the session read timeout fires."""
    return McpError(
        ErrorData(
            code=408,
            message="Timed out while waiting for response to ClientRequest. Waited 3.0 seconds.",
        )
    )


def _make_in_flight_client(call_tool_error: BaseException | None = None):
    """Fake client whose tools/call takes the session's next request id, then fails.

    Without an error the call never returns, like a long-running remote tool.
    """
    client = _make_client()
    client.session._request_id = _IN_FLIGHT_REQUEST_ID

    async def _call_tool(*args, **kwargs):
        # The SDK assigns the next id when it sends the request.
        client.session._request_id += 1
        if call_tool_error is not None:
            raise call_tool_error
        await asyncio.Event().wait()

    client.call_tool = _call_tool
    client.cancel = AsyncMock()
    client.ping = AsyncMock(return_value=True)
    return client


# ---------------------------------------------------------------------------
# describe — success paths
# ---------------------------------------------------------------------------


async def test_describe_returns_description_and_schema():
    tool = FakeTool(
        name="search",
        description="Search the web.",
        inputSchema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client))

    result = await gateway.describe(_mcp_data("search"))

    assert result.description == "[external MCP tool description] Search the web."
    assert result.input_schema == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }


async def test_describe_falls_back_to_tool_name_when_description_empty():
    tool = FakeTool(name="do_thing", description="")
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client))

    result = await gateway.describe(_mcp_data("do_thing"))

    assert result.description == "do_thing"


async def test_describe_falls_back_to_tool_name_when_description_whitespace_only():
    tool = FakeTool(name="do_thing", description="   ")
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client))

    result = await gateway.describe(_mcp_data("do_thing"))

    assert result.description == "do_thing"


async def test_describe_returns_empty_schema_when_input_schema_none():
    tool = FakeTool(name="no_schema", description="Tool.")
    tool.inputSchema = None
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client))

    result = await gateway.describe(_mcp_data("no_schema"))

    assert result.input_schema == {}


# ---------------------------------------------------------------------------
# describe — failure paths
# ---------------------------------------------------------------------------


async def test_describe_truncates_long_description_strips_control_chars_and_prefixes():
    raw_description = "A" * 2000 + "\x00\x07\x1f evil\x7f content" + "B" * 100
    tool = FakeTool(name="search", description=raw_description)
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client))

    result = await gateway.describe(_mcp_data("search"))

    prefix = "[external MCP tool description] "
    assert result.description.startswith(prefix)
    assert len(result.description) == len(prefix) + 1024
    assert "\x00" not in result.description
    assert "\x07" not in result.description
    assert "\x1f" not in result.description
    assert "\x7f" not in result.description


async def test_describe_leaves_input_schema_unchanged_when_description_truncated():
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    tool = FakeTool(name="search", description="A" * 2000, inputSchema=schema)
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client))

    result = await gateway.describe(_mcp_data("search"))

    assert result.input_schema == schema


async def test_describe_raises_mcp_tool_error_when_tool_not_found():
    tool = FakeTool(name="other_tool")
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client))

    with pytest.raises(McpToolError, match="not found"):
        await gateway.describe(_mcp_data("missing_tool"))


async def test_describe_raises_mcp_tool_error_on_connection_failure():
    client = _make_client(raise_on_enter=ConnectionError("refused"))
    gateway = McpToolGateway(_factory(client))

    with pytest.raises(McpToolError, match="unreachable"):
        await gateway.describe(_mcp_data("any_tool"))


# ---------------------------------------------------------------------------
# call — success paths
# ---------------------------------------------------------------------------


async def test_call_returns_structured_content_as_json():
    result = FakeCallResult(structured_content={"answer": 42})
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client))

    output = await gateway.call(_mcp_data("search"), {"query": "hello"})

    assert json.loads(output) == {"answer": 42}


async def test_call_returns_text_content_joined():
    result = FakeCallResult(content=[FakeTextContent("hello"), FakeTextContent("world")])
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client))

    output = await gateway.call(_mcp_data("search"), {})

    assert output == "hello world"


async def test_call_renders_image_content_marker():
    result = FakeCallResult(content=[FakeImageContent(data="QUJDRA==")])
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client))

    output = await gateway.call(_mcp_data("screenshot"), {})

    assert output  # non-empty
    assert "image" in output
    assert "image/png" in output
    assert "omitted" in output


async def test_call_renders_mixed_text_and_image():
    result = FakeCallResult(
        content=[FakeTextContent("Here is the page"), FakeImageContent(data="QUJD")]
    )
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client))

    output = await gateway.call(_mcp_data("screenshot"), {})

    assert output.startswith("Here is the page")
    assert "omitted" in output


async def test_call_renders_resource_link_marker():
    result = FakeCallResult(content=[FakeResourceLink(uri="file:///x.png")])
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client))

    output = await gateway.call(_mcp_data("fetch_resource"), {})

    assert "resource_link" in output
    assert "file:///x.png" in output
    assert "omitted" in output


async def test_call_falls_back_to_str_data():
    result = FakeCallResult(data={"raw": "value"})
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client))

    output = await gateway.call(_mcp_data("search"), {})

    assert "raw" in output


# ---------------------------------------------------------------------------
# call — failure paths
# ---------------------------------------------------------------------------


async def test_call_raises_mcp_tool_error_on_is_error():
    result = FakeCallResult(is_error=True, data="something went wrong")
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client))

    with pytest.raises(McpToolError, match="something went wrong"):
        await gateway.call(_mcp_data("search"), {})


async def test_call_raises_mcp_tool_error_on_connection_failure():
    client = _make_client(raise_on_enter=ConnectionError("network down"))
    gateway = McpToolGateway(_factory(client))

    with pytest.raises(McpToolError, match="MCP call failed"):
        await gateway.call(_mcp_data("search"), {})


# ---------------------------------------------------------------------------
# call — cancelling the in-flight request on the server
# ---------------------------------------------------------------------------


async def test_call_cancels_in_flight_request_when_sdk_read_timeout_fires():
    client = _make_in_flight_client(_sdk_read_timeout())
    gateway = McpToolGateway(_factory(client))

    with pytest.raises(McpToolError, match=r"MCP call failed.*Timed out"):
        await gateway.call(_mcp_data("browse"), {})

    client.cancel.assert_awaited_once()
    assert client.cancel.await_args.args == (_IN_FLIGHT_REQUEST_ID,)


@pytest.mark.parametrize(
    ("call_tool_error", "surfaced_error"),
    [
        (_sdk_read_timeout(), McpToolError),
        (asyncio.CancelledError(), asyncio.CancelledError),
    ],
    ids=["sdk_read_timeout", "cancelled"],
)
async def test_call_pings_after_cancel_and_before_closing_the_session(
    call_tool_error, surfaced_error
):
    client = _make_in_flight_client(call_tool_error)
    gateway = McpToolGateway(_factory(client))

    with pytest.raises(surfaced_error):
        await gateway.call(_mcp_data("browse"), {})

    session_steps = [
        name for name, _, _ in client.mock_calls if name in {"cancel", "ping", "__aexit__"}
    ]
    assert session_steps == ["cancel", "ping", "__aexit__"]


async def test_call_cancels_in_flight_request_when_caller_cancels():
    client = _make_in_flight_client()
    gateway = McpToolGateway(_factory(client))

    # Same shape as the agent loop's per-tool timeout: wait_for cancels the call.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(gateway.call(_mcp_data("browse"), {}), timeout=0.05)

    client.cancel.assert_awaited_once()
    assert client.cancel.await_args.args == (_IN_FLIGHT_REQUEST_ID,)


async def test_call_sends_cancel_when_cancelled_by_an_anyio_scope():
    client = _make_in_flight_client()
    cancels_delivered = []

    async def _send_cancel(*args, **kwargs):
        # A checkpoint: an unshielded send is cancelled here by the expired scope.
        await asyncio.sleep(0)
        cancels_delivered.append(args)

    client.cancel.side_effect = _send_cancel
    gateway = McpToolGateway(_factory(client))

    with anyio.move_on_after(0.05):
        await gateway.call(_mcp_data("browse"), {})

    assert cancels_delivered == [(_IN_FLIGHT_REQUEST_ID,)]


@pytest.mark.parametrize(
    "call_tool_error",
    [
        McpError(ErrorData(code=INTERNAL_ERROR, message="server exploded")),
        ConnectionError("connection reset"),
    ],
    ids=["json_rpc_error_response", "connection_error"],
)
async def test_call_does_not_cancel_when_request_failed_without_timing_out(call_tool_error):
    client = _make_in_flight_client(call_tool_error)
    gateway = McpToolGateway(_factory(client))

    with pytest.raises(McpToolError, match="MCP call failed"):
        await gateway.call(_mcp_data("browse"), {})

    client.cancel.assert_not_awaited()
    client.ping.assert_not_awaited()


@pytest.mark.parametrize("failing_step", ["cancel", "ping"])
async def test_call_surfaces_timeout_error_when_cancel_send_fails(failing_step):
    client = _make_in_flight_client(_sdk_read_timeout())
    getattr(client, failing_step).side_effect = ConnectionError("server gone")
    gateway = McpToolGateway(_factory(client))

    with pytest.raises(McpToolError, match="Timed out") as error_info:
        await gateway.call(_mcp_data("browse"), {})

    assert isinstance(error_info.value.__cause__, McpError)


@pytest.mark.parametrize("failing_step", ["cancel", "ping"])
async def test_call_propagates_cancelled_error_when_cancel_send_fails(failing_step):
    client = _make_in_flight_client(asyncio.CancelledError())
    getattr(client, failing_step).side_effect = ConnectionError("server gone")
    gateway = McpToolGateway(_factory(client))

    with pytest.raises(asyncio.CancelledError):
        await gateway.call(_mcp_data("browse"), {})


@pytest.mark.parametrize(
    ("call_tool_error", "caller_timeout", "surfaced_error"),
    [
        (_sdk_read_timeout(), None, McpToolError),
        (None, 0.05, TimeoutError),
    ],
    ids=["sdk_read_timeout", "caller_cancels"],
)
@pytest.mark.parametrize("hanging_step", ["cancel", "ping"])
async def test_call_gives_up_on_cancel_send_after_deadline(
    monkeypatch, hanging_step, call_tool_error, caller_timeout, surfaced_error
):
    monkeypatch.setattr(gateway_module, "_CANCEL_SEND_TIMEOUT_SECONDS", 0.05)
    client = _make_in_flight_client(call_tool_error)

    async def _unresponsive_server(*args, **kwargs):
        await asyncio.Event().wait()

    getattr(client, hanging_step).side_effect = _unresponsive_server
    gateway = McpToolGateway(_factory(client))
    started = time.monotonic()

    with pytest.raises(surfaced_error):
        # Outer bound so a missing deadline fails the test instead of hanging the suite.
        async with asyncio.timeout(2):
            await asyncio.wait_for(gateway.call(_mcp_data("browse"), {}), timeout=caller_timeout)

    assert time.monotonic() - started < 1


# ---------------------------------------------------------------------------
# SDK contract the gateway depends on
# ---------------------------------------------------------------------------


async def test_sdk_sends_tools_call_with_the_request_id_read_right_before_it():
    """Pin the SDK assumption McpToolGateway.call relies on to cancel a tool call.

    The gateway reads the private ClientSession._request_id right before call_tool
    and treats it as the tools/call JSON-RPC id. A real in-memory server checks
    that against the id the server actually receives, so an SDK change that
    renames the counter or changes when ids are assigned fails here.
    """
    server = FastMCP("contract")
    ids_seen_by_server = []

    @server.tool
    async def echo(ctx: Context) -> str:
        ids_seen_by_server.append(ctx.request_id)
        return "ok"

    async with Client(server) as client:
        expected_request_id = client.session._request_id
        await client.call_tool("echo", {})

    assert ids_seen_by_server == [str(expected_request_id)]
