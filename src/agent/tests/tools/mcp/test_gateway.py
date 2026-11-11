"""
Tests for McpToolGateway.

Mocks the FastMCPClientFactory and fastmcp Client to avoid real network I/O; the
round-trip and SDK-contract tests at the end use a real in-memory FastMCP server.
"""

from __future__ import annotations

import asyncio
import hashlib
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
from fastmcp import Client, FastMCP
from mcp import MCPError
from mcp.types import INTERNAL_ERROR, REQUEST_TIMEOUT, ImageContent, TextContent
from shared.models.tools import McpToolData

from tests.log_capture import assert_masked_exception, capture_logs_at, log_line_starting_with
from tests.secret_sealing import agent_cryptographer, seal, seal_with_foreign_key

# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


def _mcp_data(tool_name: str = "search") -> McpToolData:
    return McpToolData(transport="http://localhost/sse", tool_name=tool_name)


@dataclass
class FakeTool:
    name: str
    description: str = "A fake tool."
    input_schema: dict = field(default_factory=lambda: {"type": "object", "properties": {}})


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
    mime_type: str = "image/png"


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


def _sdk_read_timeout() -> MCPError:
    """The error mcp's send_request raises when the session read timeout fires."""
    return MCPError(code=REQUEST_TIMEOUT, message="Request 'tools/call' timed out")


def _make_in_flight_client(
    call_tool_error: BaseException | None = None, protocol_version: str = "2025-11-25"
):
    """Fake client whose tools/call fails with ``call_tool_error``.

    Without an error the call never returns, like a long-running remote tool.
    """
    client = _make_client()
    client.protocol_version = protocol_version

    async def _call_tool(*args, **kwargs):
        if call_tool_error is not None:
            raise call_tool_error
        await asyncio.Event().wait()

    client.call_tool = _call_tool
    client.ping = AsyncMock(return_value=True)
    return client


# ---------------------------------------------------------------------------
# describe — success paths
# ---------------------------------------------------------------------------


async def test_describe_returns_description_and_schema():
    tool = FakeTool(
        name="search",
        description="Search the web.",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    result = await gateway.describe(_mcp_data("search"))

    assert result.description == "[external MCP tool description] Search the web."
    assert result.input_schema == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }


async def test_describe_falls_back_to_tool_name_when_description_empty():
    tool = FakeTool(name="do_thing", description="")
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    result = await gateway.describe(_mcp_data("do_thing"))

    assert result.description == "[external MCP tool description] do_thing"


async def test_describe_falls_back_to_tool_name_when_description_whitespace_only():
    tool = FakeTool(name="do_thing", description="   ")
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    result = await gateway.describe(_mcp_data("do_thing"))

    assert result.description == "[external MCP tool description] do_thing"


async def test_describe_returns_empty_schema_when_input_schema_none():
    tool = FakeTool(name="no_schema", description="Tool.")
    tool.input_schema = None
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    result = await gateway.describe(_mcp_data("no_schema"))

    assert result.input_schema == {}


# ---------------------------------------------------------------------------
# describe — failure paths
# ---------------------------------------------------------------------------


async def test_describe_truncates_long_description_strips_control_chars_and_prefixes():
    raw_description = "A" * 2000 + "\x00\x07\x1f evil\x7f content" + "B" * 100
    tool = FakeTool(name="search", description=raw_description)
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    result = await gateway.describe(_mcp_data("search"))

    prefix = "[external MCP tool description] "
    assert result.description.startswith(prefix)
    assert len(result.description) == len(prefix) + 1024
    assert "\x00" not in result.description
    assert "\x07" not in result.description
    assert "\x1f" not in result.description
    assert "\x7f" not in result.description


async def test_describe_cleans_the_input_schema():
    schema = {
        "type": "object",
        "properties": {"q": {"type": "string", "description": "Look\x1b[31m\x07 up" + "x" * 2000}},
    }
    tool = FakeTool(name="search", input_schema=schema)
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    result = await gateway.describe(_mcp_data("search"))

    assert result.input_schema == {
        "type": "object",
        "properties": {"q": {"type": "string", "description": "Look[31m up" + "x" * 1013}},
    }


async def test_describe_refuses_a_tool_whose_schema_key_has_control_characters():
    schema = {"type": "object", "properties": {"q\x07": {"type": "string"}}}
    tool = FakeTool(name="search", input_schema=schema)
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(McpToolError, match=r"unsafe input schema: schema key 'q\\x07' contains control"):
        await gateway.describe(_mcp_data("search"))


async def test_describe_leaves_input_schema_unchanged_when_description_truncated():
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    tool = FakeTool(name="search", description="A" * 2000, input_schema=schema)
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    result = await gateway.describe(_mcp_data("search"))

    assert result.input_schema == schema


async def test_describe_raises_mcp_tool_error_when_tool_not_found():
    tool = FakeTool(name="other_tool")
    client = _make_client(list_tools_result=[tool])
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(McpToolError, match="not found"):
        await gateway.describe(_mcp_data("missing_tool"))


async def test_describe_raises_mcp_tool_error_on_connection_failure():
    client = _make_client(raise_on_enter=ConnectionError("refused"))
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(McpToolError, match="unreachable"):
        await gateway.describe(_mcp_data("any_tool"))


async def test_describe_names_the_error_class_when_the_error_has_no_message():
    client = _make_client(raise_on_enter=TimeoutError())
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(McpToolError) as error_info:
        await gateway.describe(_mcp_data("search"))

    assert str(error_info.value) == "MCP server unreachable for tool_name=search: TimeoutError"


# ---------------------------------------------------------------------------
# describe — caching
# ---------------------------------------------------------------------------


class _CountingFactory:
    """Hands out one fresh fake client per connect; ``outcomes`` is consumed in order."""

    def __init__(self, outcomes: list) -> None:
        self._outcomes = outcomes
        self.connects = 0

    def create(self, data: McpToolData):
        self.connects += 1
        outcome = self._outcomes.pop(0) if self._outcomes else [FakeTool(name=data.tool_name)]
        if isinstance(outcome, BaseException):
            return _make_client(raise_on_enter=outcome)
        return _make_client(list_tools_result=outcome)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(("elapsed_s", "expected_connects"), [(299.9, 1), (300.0, 2)])
async def test_describe_reuses_a_result_for_five_minutes(elapsed_s, expected_connects):
    factory = _CountingFactory([[FakeTool(name="search", description="Search.")]])
    clock = _FakeClock()
    gateway = McpToolGateway(factory, agent_cryptographer(), clock=clock, describe_cache_ttl_s=300)

    first = await gateway.describe(_mcp_data("search"))
    clock.now += elapsed_s
    second = await gateway.describe(_mcp_data("search"))

    assert factory.connects == expected_connects
    assert second.input_schema == first.input_schema


async def test_describe_does_not_share_results_between_credentials():
    factory = _CountingFactory([])
    gateway = McpToolGateway(
        factory, agent_cryptographer(), clock=_FakeClock(), describe_cache_ttl_s=300
    )
    data = _mcp_data("search")

    await gateway.describe(data.model_copy(update={"auth": seal("token-org-a")}))
    await gateway.describe(data.model_copy(update={"auth": seal("token-org-b")}))

    assert factory.connects == 2


async def test_describe_shares_one_result_between_sealings_of_one_credential():
    factory = _CountingFactory([])
    gateway = McpToolGateway(
        factory, agent_cryptographer(), clock=_FakeClock(), describe_cache_ttl_s=300
    )
    data = _mcp_data("search")

    with capture_logs_at("DEBUG") as messages:
        # django_app seals the token afresh for every run.
        await gateway.describe(data.model_copy(update={"auth": seal("token-org-a")}))
        await gateway.describe(data.model_copy(update={"auth": seal("token-org-a")}))

    assert factory.connects == 1
    logged = "\n".join(messages)
    assert "token-org-a" not in logged
    assert hashlib.sha256(b"token-org-a").hexdigest() not in logged


@pytest.mark.parametrize(
    "auth",
    [seal_with_foreign_key("token-org-a"), "not-a-fernet-token"],
    ids=["sealed-under-another-key", "not-a-token"],
)
async def test_describe_with_undecryptable_auth_fails_before_connecting(auth):
    factory = _CountingFactory([])
    gateway = McpToolGateway(
        factory, agent_cryptographer(), clock=_FakeClock(), describe_cache_ttl_s=300
    )

    with pytest.raises(McpToolError) as error_info:
        await gateway.describe(_mcp_data("search").model_copy(update={"auth": auth}))

    assert str(error_info.value) == "MCP tool 'search': auth could not be decrypted."
    assert factory.connects == 0


@pytest.mark.parametrize(
    "failure",
    [
        ConnectionError("refused"),
        [FakeTool(name="other_tool")],
        [FakeTool(name="search", input_schema={"properties": {"q\x07": {"type": "string"}}})],
    ],
    ids=["unreachable", "tool-missing", "unsafe-schema"],
)
async def test_failed_describe_is_not_cached(failure):
    factory = _CountingFactory([failure])
    gateway = McpToolGateway(
        factory, agent_cryptographer(), clock=_FakeClock(), describe_cache_ttl_s=300
    )

    with pytest.raises(McpToolError):
        await gateway.describe(_mcp_data("search"))
    result = await gateway.describe(_mcp_data("search"))

    assert factory.connects == 2
    assert result.description == "[external MCP tool description] A fake tool."


async def test_describe_cache_evicts_the_oldest_entry_when_full():
    factory = _CountingFactory([])
    gateway = McpToolGateway(
        factory,
        agent_cryptographer(),
        clock=_FakeClock(),
        max_cached_descriptions=2,
        describe_cache_ttl_s=300,
    )

    for tool_name in ("a", "b", "c"):
        await gateway.describe(_mcp_data(tool_name))
    await gateway.describe(_mcp_data("c"))
    await gateway.describe(_mcp_data("a"))

    assert factory.connects == 4


async def test_mutating_a_described_schema_does_not_change_the_cached_one():
    factory = _CountingFactory([])
    gateway = McpToolGateway(
        factory, agent_cryptographer(), clock=_FakeClock(), describe_cache_ttl_s=300
    )

    for _ in range(2):
        described = await gateway.describe(_mcp_data("search"))
        described.input_schema["properties"]["injected"] = {"type": "string"}
    latest = await gateway.describe(_mcp_data("search"))

    assert latest.input_schema == {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# call — success paths
# ---------------------------------------------------------------------------


async def test_call_returns_structured_content_as_json():
    result = FakeCallResult(structured_content={"answer": 42})
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    output = await gateway.call(_mcp_data("search"), {"query": "hello"})

    assert json.loads(output) == {"answer": 42}


async def test_call_returns_text_content_joined():
    result = FakeCallResult(content=[FakeTextContent("hello"), FakeTextContent("world")])
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    output = await gateway.call(_mcp_data("search"), {})

    assert output == "hello world"


async def test_call_renders_image_content_marker():
    result = FakeCallResult(content=[FakeImageContent(data="QUJDRA==")])
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

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
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    output = await gateway.call(_mcp_data("screenshot"), {})

    assert output.startswith("Here is the page")
    assert "omitted" in output


async def test_call_renders_resource_link_marker():
    result = FakeCallResult(content=[FakeResourceLink(uri="file:///x.png")])
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    output = await gateway.call(_mcp_data("fetch_resource"), {})

    assert "resource_link" in output
    assert "file:///x.png" in output
    assert "omitted" in output


async def test_call_falls_back_to_str_data():
    result = FakeCallResult(data={"raw": "value"})
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    output = await gateway.call(_mcp_data("search"), {})

    assert "raw" in output


# ---------------------------------------------------------------------------
# call — failure paths
# ---------------------------------------------------------------------------


async def test_call_raises_mcp_tool_error_on_is_error():
    result = FakeCallResult(is_error=True, data="something went wrong")
    client = _make_client(call_tool_result=result)
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(McpToolError, match="something went wrong"):
        await gateway.call(_mcp_data("search"), {})


async def test_call_raises_mcp_tool_error_on_connection_failure():
    client = _make_client(raise_on_enter=ConnectionError("network down"))
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(McpToolError, match="MCP call failed"):
        await gateway.call(_mcp_data("search"), {})


async def test_call_names_the_error_class_when_the_error_has_no_message():
    client = _make_in_flight_client(TimeoutError())
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(McpToolError) as error_info:
        await gateway.call(_mcp_data("browse"), {})

    assert str(error_info.value) == "MCP call failed for tool_name=browse: TimeoutError"


# ---------------------------------------------------------------------------
# call — confirming the SDK's cancel reached the server before the session closes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("call_tool_error", "surfaced_error"),
    [
        (_sdk_read_timeout(), McpToolError),
        (asyncio.CancelledError(), asyncio.CancelledError),
    ],
    ids=["sdk_read_timeout", "cancelled"],
)
async def test_call_pings_before_closing_the_session_when_abandoned(
    call_tool_error, surfaced_error
):
    client = _make_in_flight_client(call_tool_error)
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(surfaced_error):
        await gateway.call(_mcp_data("browse"), {})

    session_steps = [name for name, _, _ in client.mock_calls if name in {"ping", "__aexit__"}]
    assert session_steps == ["ping", "__aexit__"]


async def test_call_pings_when_caller_cancels():
    client = _make_in_flight_client()
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    # Same shape as the agent loop's per-tool timeout: wait_for cancels the call.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(gateway.call(_mcp_data("browse"), {}), timeout=0.05)

    client.ping.assert_awaited_once()


async def test_call_pings_when_cancelled_by_an_anyio_scope():
    client = _make_in_flight_client()
    pings_delivered = []

    async def _ping(*args, **kwargs):
        # A checkpoint: an unshielded ping is cancelled here by the expired scope.
        await asyncio.sleep(0)
        pings_delivered.append(True)
        return True

    client.ping.side_effect = _ping
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with anyio.move_on_after(0.05):
        await gateway.call(_mcp_data("browse"), {})

    assert pings_delivered == [True]


@pytest.mark.parametrize(
    "call_tool_error",
    [
        MCPError(code=INTERNAL_ERROR, message="server exploded"),
        ConnectionError("connection reset"),
    ],
    ids=["json_rpc_error_response", "connection_error"],
)
async def test_call_does_not_ping_when_request_failed_without_timing_out(call_tool_error):
    client = _make_in_flight_client(call_tool_error)
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(McpToolError, match="MCP call failed"):
        await gateway.call(_mcp_data("browse"), {})

    client.ping.assert_not_awaited()


@pytest.mark.parametrize(
    ("call_tool_error", "surfaced_error"),
    [
        (_sdk_read_timeout(), McpToolError),
        (asyncio.CancelledError(), asyncio.CancelledError),
    ],
    ids=["sdk_read_timeout", "cancelled"],
)
async def test_call_does_not_ping_on_the_stateless_protocol(call_tool_error, surfaced_error):
    client = _make_in_flight_client(call_tool_error, protocol_version="2026-07-28")
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(surfaced_error):
        await gateway.call(_mcp_data("browse"), {})

    client.ping.assert_not_awaited()


async def test_call_surfaces_timeout_error_when_ping_fails():
    client = _make_in_flight_client(_sdk_read_timeout())
    client.ping.side_effect = ConnectionError("server gone")
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with pytest.raises(McpToolError, match="timed out") as error_info:
        await gateway.call(_mcp_data("browse"), {})

    assert isinstance(error_info.value.__cause__, MCPError)


async def test_call_propagates_cancelled_error_when_ping_fails():
    client = _make_in_flight_client(asyncio.CancelledError())
    client.ping.side_effect = ConnectionError("server gone")
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

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
async def test_call_gives_up_on_ping_after_deadline(
    monkeypatch, call_tool_error, caller_timeout, surfaced_error
):
    monkeypatch.setattr(gateway_module, "_CANCEL_CONFIRM_TIMEOUT_SECONDS", 0.05)
    client = _make_in_flight_client(call_tool_error)

    async def _unresponsive_server(*args, **kwargs):
        await asyncio.Event().wait()

    client.ping.side_effect = _unresponsive_server
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)
    started = time.monotonic()

    with pytest.raises(surfaced_error):
        # Outer bound so a missing deadline fails the test instead of hanging the suite.
        async with asyncio.timeout(2):
            await asyncio.wait_for(gateway.call(_mcp_data("browse"), {}), timeout=caller_timeout)

    assert time.monotonic() - started < 1


async def test_failed_ping_logs_class_name_and_digest_only():
    """A transport error raised while confirming the cancel can quote the server URL
    and its auth header; the WARNING line names the class and digests the message."""
    secret_marker = "SENSITIVE_MCP_BEARER_TOKEN_86420"
    client = _make_in_flight_client(_sdk_read_timeout())
    client.ping.side_effect = ConnectionError(f"POST failed: {secret_marker}")
    gateway = McpToolGateway(_factory(client), agent_cryptographer(), describe_cache_ttl_s=300)

    with capture_logs_at("WARNING") as logs:
        with pytest.raises(McpToolError):
            await gateway.call(_mcp_data("browse"), {})

    warning_line = log_line_starting_with(logs, "Failed to confirm MCP cancel for tool_name=")
    assert secret_marker not in warning_line
    assert "tool_name=browse" in warning_line
    assert_masked_exception(warning_line, "ConnectionError")


# ---------------------------------------------------------------------------
# A real in-memory MCP server: the SDK types and the cancel contract the gateway
# depends on. A fake mirrors the SDK as it was when written; these fail when it moves.
# ---------------------------------------------------------------------------


class _InMemoryFactory:
    """Connects the gateway to an in-process FastMCP server instead of a URL."""

    def __init__(self, server: FastMCP, mode: str = "auto") -> None:
        self._server = server
        self._mode = mode

    def create(self, data: McpToolData) -> Client:
        return Client(self._server, timeout=data.timeout, mode=self._mode)


# "legacy" forces the initialize handshake; "auto", the Client default, lands on the
# stateless protocol against a FastMCP 4 server.
_PROTOCOL_MODES = pytest.mark.parametrize(
    "mode", ["legacy", "auto"], ids=["handshake_protocol", "stateless_protocol"]
)


def _real_server() -> FastMCP:
    server = FastMCP("round-trip")

    @server.tool
    def search(query: str) -> str:
        """Search the web."""
        return f"results for {query}"

    @server.tool
    def screenshot() -> list:
        return [
            TextContent(type="text", text="Here is the page"),
            ImageContent(type="image", data="QUJD", mime_type="image/png"),
        ]

    return server


@_PROTOCOL_MODES
async def test_describe_reads_a_real_server_tool(mode):
    gateway = McpToolGateway(
        _InMemoryFactory(_real_server(), mode), agent_cryptographer(), describe_cache_ttl_s=300
    )

    described = await gateway.describe(_mcp_data("search"))

    assert described.description == "[external MCP tool description] Search the web."
    assert described.input_schema["properties"] == {"query": {"type": "string"}}
    assert described.input_schema["required"] == ["query"]


@pytest.mark.parametrize(
    ("tool_name", "args", "expected_output"),
    [
        ("search", {"query": "cats"}, '{"result": "results for cats"}'),
        ("screenshot", {}, "Here is the page [image omitted: image/png, ~1KB]"),
    ],
    ids=["structured_content", "text_and_image_blocks"],
)
@_PROTOCOL_MODES
async def test_call_renders_a_real_server_result(mode, tool_name, args, expected_output):
    gateway = McpToolGateway(
        _InMemoryFactory(_real_server(), mode), agent_cryptographer(), describe_cache_ttl_s=300
    )

    output = await gateway.call(_mcp_data(tool_name), args)

    assert output == expected_output


def _server_with_a_tool_that_never_returns() -> tuple[FastMCP, anyio.Event, anyio.Event]:
    server = FastMCP("contract")
    started = anyio.Event()
    cancelled = anyio.Event()

    @server.tool
    async def browse() -> str:
        started.set()
        try:
            await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            cancelled.set()
            raise
        return "unreachable"

    return server, started, cancelled


@_PROTOCOL_MODES
async def test_sdk_cancels_the_server_tool_when_the_read_timeout_fires(mode):
    """Pin the SDK behaviour McpToolGateway.call relies on instead of sending its own
    cancel: a tools/call abandoned on the read timeout is cancelled on the server.
    The check runs while the session is still open, so closing it cannot be what
    stopped the tool."""
    server, _, cancelled = _server_with_a_tool_that_never_returns()

    async with Client(server, timeout=0.2, mode=mode) as client:
        with pytest.raises(MCPError) as error_info:
            await client.call_tool("browse", {})

        with anyio.fail_after(2):
            await cancelled.wait()

    assert error_info.value.code == REQUEST_TIMEOUT


@_PROTOCOL_MODES
async def test_sdk_cancels_the_server_tool_when_the_caller_cancels(mode):
    server, started, cancelled = _server_with_a_tool_that_never_returns()

    async with Client(server, mode=mode) as client:
        call = asyncio.create_task(client.call_tool("browse", {}))
        with anyio.fail_after(2):
            await started.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call

        with anyio.fail_after(2):
            await cancelled.wait()


@_PROTOCOL_MODES
async def test_call_timeout_on_a_real_server_confirms_the_cancel_without_warnings(mode):
    server, _, _ = _server_with_a_tool_that_never_returns()
    gateway = McpToolGateway(
        _InMemoryFactory(server, mode), agent_cryptographer(), describe_cache_ttl_s=300
    )
    data = _mcp_data("browse").model_copy(update={"timeout": 0.2})

    with capture_logs_at("WARNING") as logs:
        with pytest.raises(McpToolError, match="timed out"):
            await gateway.call(data, {})

    assert logs == []
