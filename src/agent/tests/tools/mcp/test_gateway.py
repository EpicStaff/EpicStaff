"""
Tests for McpToolGateway.

Mocks the FastMCPClientFactory and fastmcp Client to avoid real network I/O.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import McpToolError
from app.tools.mcp.client_factory import FastMCPClientFactory
from app.tools.mcp.gateway import McpToolGateway
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
    inputSchema: dict = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


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

    assert result.description == "Search the web."
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
    result = FakeCallResult(
        content=[FakeTextContent("hello"), FakeTextContent("world")]
    )
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
