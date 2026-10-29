from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus

import anyio
from fastmcp import Client
from loguru import logger
from mcp import McpError

from app.exceptions import McpToolError
from app.logging_utils import format_exception_for_log
from app.tools.mcp.client_factory import FastMCPClientFactory
from app.tools.mcp.schema_sanitizer import (
    MAX_TEXT_CHARS,
    UnsafeSchemaError,
    sanitize_input_schema,
    strip_control_chars,
)
from shared.models.tools import McpToolData

_CANCEL_SEND_TIMEOUT_SECONDS = 5
_MAX_CACHED_DESCRIPTIONS = 256


@dataclass
class McpToolDescription:
    description: str
    input_schema: dict


class McpToolGateway:
    """Information Expert for MCP server I/O.

    Holds the factory and exposes two async operations — describe and call —
    that map directly to list_tools / call_tool on the MCP server.  Neither
    method knows about ToolResult; that adaptation lives in McpToolExecutor.
    """

    def __init__(
        self,
        factory: FastMCPClientFactory,
        *,
        describe_cache_ttl_s: float,
        clock: Callable[[], float] = time.monotonic,
        max_cached_descriptions: int = _MAX_CACHED_DESCRIPTIONS,
    ) -> None:
        self._factory = factory
        self._describe_cache_ttl_s = describe_cache_ttl_s
        self._clock = clock
        self._max_cached_descriptions = max_cached_descriptions
        self._describe_cache: dict[str, tuple[float, McpToolDescription]] = {}

    async def describe(self, data: McpToolData) -> McpToolDescription:
        """Fetch tool metadata from the MCP server, reusing a success for the cache TTL.

        Results are cached per (transport, auth, tool name), so a run that resolves
        several tools of one server, or back-to-back runs, do not reconnect each time.
        Failures are not cached.

        Raises McpToolError if the server is unreachable, the tool is absent, or its
        input schema is unsafe (see sanitize_input_schema).
        """
        cache_key = self._describe_cache_key(data)
        now = self._clock()
        cached = self._describe_cache.get(cache_key)

        if cached is not None and cached[0] > now:
            return copy.deepcopy(cached[1])

        description = await self._fetch_description(data)
        self._store_description(cache_key, description, now)
        return copy.deepcopy(description)

    @staticmethod
    def _describe_cache_key(data: McpToolData) -> str:
        # Hashed so neither the auth token nor a credential in the URL sits in the key.
        identity = json.dumps([data.transport, data.auth, data.tool_name])
        return hashlib.sha256(identity.encode()).hexdigest()

    def _store_description(
        self, cache_key: str, description: McpToolDescription, now: float
    ) -> None:
        self._describe_cache = {
            key: entry for key, entry in self._describe_cache.items() if entry[0] > now
        }
        self._describe_cache.pop(cache_key, None)

        if len(self._describe_cache) >= self._max_cached_descriptions:
            oldest_key = next(iter(self._describe_cache))
            del self._describe_cache[oldest_key]

        self._describe_cache[cache_key] = (now + self._describe_cache_ttl_s, description)

    async def _fetch_description(self, data: McpToolData) -> McpToolDescription:
        client = self._factory.create(data)

        try:
            async with client:
                tools = await client.list_tools()

        except Exception as error:
            raise McpToolError(
                f"MCP server unreachable for tool_name={data.tool_name}: {error}"
            ) from error

        tool = next((t for t in tools if t.name == data.tool_name), None)

        if tool is None:
            raise McpToolError(
                f"Tool '{data.tool_name}' not found on MCP server at {data.transport!r}"
            )

        # The input schema reaches the model next to the description, so it gets the
        # same cleaning; the marker goes on the description even when the server
        # sent none, since the schema is external text all the same.
        cleaned = strip_control_chars(tool.description or "").strip()[:MAX_TEXT_CHARS]
        description = f"[external MCP tool description] {cleaned or data.tool_name}"

        try:
            input_schema = sanitize_input_schema(dict(tool.inputSchema)) if tool.inputSchema else {}
        except UnsafeSchemaError as error:
            # No transport here: the URL can carry credentials, and this message
            # reaches the client through the run's error event.
            raise McpToolError(
                f"MCP tool '{data.tool_name}' has an unsafe input schema: {error}"
            ) from error

        return McpToolDescription(description=description, input_schema=input_schema)

    @staticmethod
    def _render_content_block(block) -> str:
        text = getattr(block, "text", None)
        if text is not None:
            return text

        btype = getattr(block, "type", None) or type(block).__name__
        data = getattr(block, "data", None)
        mime = getattr(block, "mimeType", None)

        if isinstance(data, str) and data:
            kb = max(1, (len(data) * 3 // 4) // 1024)  # base64 -> ~bytes -> KB
            return f"[{btype} omitted: {mime or 'unknown'}, ~{kb}KB]"

        uri = getattr(block, "uri", None)
        if uri is not None:
            return f"[{btype} omitted: {uri}]"

        return f"[{btype} omitted]"

    async def call(self, data: McpToolData, args: dict) -> str:
        """Invoke the MCP tool and return its output as a string.

        When the call is abandoned while the server may still be running it (the
        session read timeout fires, or this coroutine is cancelled), a best-effort
        notifications/cancelled is sent before the session closes: servers on
        mcp < 1.27 keep running in-flight tools after the session ends. Sending it
        can delay the caller's own timeout (tool_timeout / max_execution_time via
        wait_for) by up to _CANCEL_SEND_TIMEOUT_SECONDS.

        Raises McpToolError on tool-reported errors, connection failures or timeouts.
        """
        client = self._factory.create(data)

        try:
            async with client:
                # Private attribute: no public API exposes an in-flight request id
                # (fastmcp 3.4.7, mcp 1.30). The value read right before the call
                # is the id the tools/call request is sent with.
                request_id = client.session._request_id
                try:
                    result = await client.call_tool(data.tool_name, arguments=args)
                except McpError as error:
                    if error.error.code == HTTPStatus.REQUEST_TIMEOUT:
                        await self._cancel_in_flight(
                            client, request_id, data.tool_name, "client read timeout"
                        )
                    raise
                except asyncio.CancelledError:
                    await self._cancel_in_flight(
                        client, request_id, data.tool_name, "client cancelled the call"
                    )
                    raise

        except Exception as error:
            raise McpToolError(
                f"MCP call failed for tool_name={data.tool_name}: {error}"
            ) from error

        if result.is_error:
            raise McpToolError(str(result.data))

        if result.structured_content:
            return json.dumps(result.structured_content)

        if result.content:
            return " ".join(self._render_content_block(c) for c in result.content)

        return str(result.data)

    @staticmethod
    async def _cancel_in_flight(
        client: Client, request_id: int, tool_name: str, reason: str
    ) -> None:
        # Shielded against anyio scope cancellation, which re-fires at every await;
        # a native asyncio cancel fires once and is already consumed here. Bounded
        # so an unresponsive server cannot stall the caller.
        with anyio.move_on_after(_CANCEL_SEND_TIMEOUT_SECONDS, shield=True) as scope:
            try:
                await client.cancel(request_id, reason=reason)
                # cancel() only queues the notification. The transports POST messages
                # in order, so the ping response proves the cancel POST completed
                # before the session's DELETE goes out on exit.
                await client.ping()
            except Exception as error:
                logger.warning(
                    "Failed to cancel MCP tool_name={} request_id={}: {}",
                    tool_name,
                    request_id,
                    format_exception_for_log(error),
                )

        if scope.cancelled_caught:
            logger.warning(
                "Timed out cancelling MCP tool_name={} request_id={}", tool_name, request_id
            )
