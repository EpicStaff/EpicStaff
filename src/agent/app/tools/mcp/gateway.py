from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import time
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import anyio
import httpx2
from fastmcp import Client
from loguru import logger
from mcp import MCPError
from mcp.types import INTERNAL_ERROR, REQUEST_TIMEOUT
from mcp.types.version import HANDSHAKE_PROTOCOL_VERSIONS

from app.exceptions import McpToolError
from app.logging_utils import (
    describe_http_status_error,
    format_exception_for_log,
    redact_urls,
    url_origin,
)
from app.tools.mcp.client_factory import FastMCPClientFactory, http_error_status
from app.tools.mcp.schema_sanitizer import (
    MAX_TEXT_CHARS,
    UnsafeSchemaError,
    sanitize_input_schema,
    strip_control_chars,
)
from shared.models.tools import McpToolData

_CANCEL_CONFIRM_TIMEOUT_SECONDS = 5
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
            async with self._connected(client, data.init_timeout):
                tools = await client.list_tools()

        except Exception as error:
            raise McpToolError(
                f"MCP server unreachable for tool_name={data.tool_name}: "
                f"{self._failure_reason(client, error)}"
            ) from error

        tool = next((t for t in tools if t.name == data.tool_name), None)

        if tool is None:
            raise McpToolError(
                f"Tool '{data.tool_name}' not found on MCP server at "
                f"{url_origin(data.transport)}"
            )

        # The input schema reaches the model next to the description, so it gets the
        # same cleaning; the marker goes on the description even when the server
        # sent none, since the schema is external text all the same.
        cleaned = strip_control_chars(tool.description or "").strip()[:MAX_TEXT_CHARS]
        description = f"[external MCP tool description] {cleaned or data.tool_name}"

        try:
            input_schema = (
                sanitize_input_schema(dict(tool.input_schema)) if tool.input_schema else {}
            )
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
        mime = getattr(block, "mime_type", None)

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
        session read timeout fires, or this coroutine is cancelled), the mcp SDK
        cancels it on the server. On a handshake-era connection that cancel is a
        separate notifications/cancelled, so a ping then confirms it was delivered
        before the session closes, because servers on mcp < 1.27 keep running
        in-flight tools after the session ends. Abandoning can delay the caller's
        own timeout (tool_timeout / max_execution_time via wait_for) by about 10 s
        at worst: the SDK bounds its shielded write of the cancel at 5 s, then the
        ping is bounded by _CANCEL_CONFIRM_TIMEOUT_SECONDS.

        Raises McpToolError on tool-reported errors, connection failures or timeouts.
        """
        client = self._factory.create(data)

        try:
            async with self._connected(client, data.init_timeout):
                try:
                    result = await client.call_tool(data.tool_name, arguments=args)
                except MCPError as error:
                    if error.code == REQUEST_TIMEOUT:
                        await self._confirm_cancel_delivered(client, data.tool_name)
                    raise
                except asyncio.CancelledError:
                    await self._confirm_cancel_delivered(client, data.tool_name)
                    raise

        except Exception as error:
            raise McpToolError(
                f"MCP call failed for tool_name={data.tool_name}: "
                f"{self._failure_reason(client, error)}"
            ) from error

        if result.is_error:
            raise McpToolError(str(result.data))

        if result.structured_content:
            return json.dumps(result.structured_content)

        if result.content:
            return " ".join(self._render_content_block(c) for c in result.content)

        return str(result.data)

    @staticmethod
    @asynccontextmanager
    async def _connected(client: Client, init_timeout: float | None):
        # fastmcp bounds only initialize by init_timeout. Before it, the SSE transport
        # waits for the server's endpoint event with no bound: the SDK's
        # sse_read_timeout (300 s) ends the read, but its error then waits on a stream
        # nothing reads yet. Lowering sse_read_timeout would also cut off a slow tool's
        # result on the same stream, so the whole connect phase is bounded here, and
        # the call after it is not.
        async with AsyncExitStack() as stack:
            # 0 means no limit, as in fastmcp.
            with anyio.move_on_after(init_timeout or None) as connect_scope:
                await stack.enter_async_context(client)
            if connect_scope.cancelled_caught:
                raise TimeoutError(
                    f"did not finish connecting within init_timeout={init_timeout:g} s"
                )
            yield

    @staticmethod
    def _failure_reason(client: Client, error: Exception) -> str:
        # Every reason reaches the run's error event or the model, and the SDK and
        # httpx2 quote URLs in their own texts (request URLs, redirect targets), which
        # can carry a credential in the userinfo, path or query: URLs are cut to their
        # origin. httpx2's status text also adds the server's reason phrase.
        if isinstance(error, httpx2.HTTPStatusError):
            return describe_http_status_error(error)
        # On the stateless protocol a read timeout surfaces as httpx2.ReadTimeout,
        # whose message is empty; the class name is then the only reason.
        reason = redact_urls(str(error)) or type(error).__name__
        # mcp 2 turns a 4xx/5xx without a JSON-RPC error into a generic
        # INTERNAL_ERROR, so the recorded status is what names the cause.
        status = http_error_status(client)
        if status and isinstance(error, MCPError) and error.code == INTERNAL_ERROR:
            return f"{reason} ({status})"
        return reason

    @staticmethod
    async def _confirm_cancel_delivered(client: Client, tool_name: str) -> None:
        # The stateless protocol has no session to outlive the call and no ping: the
        # SDK cancels by closing the request's own response stream.
        if client.protocol_version not in HANDSHAKE_PROTOCOL_VERSIONS:
            return
        # The SDK only queues its notifications/cancelled on the transport. The
        # transports POST messages in order, so the ping response proves the cancel
        # POST completed before the session's DELETE goes out on exit.
        # Shielded against anyio scope cancellation, which re-fires at every await;
        # a native asyncio cancel fires once and is already consumed here. Bounded
        # so an unresponsive server cannot stall the caller.
        with anyio.move_on_after(_CANCEL_CONFIRM_TIMEOUT_SECONDS, shield=True) as scope:
            try:
                await client.ping()
            except Exception as error:
                logger.warning(
                    "Failed to confirm MCP cancel for tool_name={}: {}",
                    tool_name,
                    format_exception_for_log(error),
                )

        if scope.cancelled_caught:
            logger.warning("Timed out confirming MCP cancel for tool_name={}", tool_name)
