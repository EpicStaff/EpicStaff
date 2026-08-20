"""
Tests for McpToolExecutor.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import McpToolError
from app.tools.executors.mcp_tool import McpToolExecutor
from app.tools.mcp.gateway import McpToolGateway
from shared.models.tools import McpToolData


def _data() -> McpToolData:
    return McpToolData(transport="http://localhost/sse", tool_name="search")


def _gateway(return_value=None, raise_error=None) -> McpToolGateway:
    gateway = MagicMock(spec=McpToolGateway)

    if raise_error is not None:
        gateway.call = AsyncMock(side_effect=raise_error)
    else:
        gateway.call = AsyncMock(return_value=return_value)

    return gateway


async def test_successful_call_returns_tool_result_not_error():
    gateway = _gateway(return_value="search results here")
    executor = McpToolExecutor(gateway, _data(), "search")

    result = await executor({"query": "test"})

    assert result.is_error is False
    assert result.content == "search results here"
    assert result.tool_call_id == ""


async def test_mcp_tool_error_returns_error_tool_result():
    error = McpToolError("server down")
    gateway = _gateway(raise_error=error)
    executor = McpToolExecutor(gateway, _data(), "search")

    result = await executor({"query": "test"})

    assert result.is_error is True
    assert "server down" in result.content
    assert result.tool_call_id == ""


async def test_error_message_is_preserved_verbatim():
    specific_message = "Tool 'search' timed out after 30s"
    error = McpToolError(specific_message)
    gateway = _gateway(raise_error=error)
    executor = McpToolExecutor(gateway, _data(), "search")

    result = await executor({})

    assert specific_message in result.content


async def test_gateway_called_with_correct_args():
    gateway = _gateway(return_value="ok")
    executor = McpToolExecutor(gateway, _data(), "search")
    args = {"query": "hello", "limit": 5}

    await executor(args)

    gateway.call.assert_awaited_once_with(_data(), args)
