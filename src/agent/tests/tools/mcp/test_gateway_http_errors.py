"""
McpToolGateway errors over real HTTP transports.

A local uvicorn server answers every request from a script; the gateway uses the
real FastMCPClientFactory, so the error text is what an agent run reports.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable
from contextlib import asynccontextmanager

import pytest
import uvicorn
from app.exceptions import McpToolError
from app.tools.mcp.client_factory import FastMCPClientFactory
from app.tools.mcp.gateway import McpToolGateway
from mcp.types import INTERNAL_ERROR
from shared.models.tools import McpToolData

from tests.secret_sealing import agent_cryptographer, seal

# Returns (status, json_body), or None to hold the request until the client gives up.
Responder = Callable[[str, dict], tuple[int, dict | None] | None]

_SECRET_TOKEN = "SECRET-BEARER-TOKEN-1357"


@asynccontextmanager
async def _http_server(respond: Responder):
    """Serve ``respond(http_method, json_rpc_request)`` on a local port.

    Yields the base URL and the Authorization header of every POST received.
    """
    post_authorizations: list[str | None] = []

    async def app(scope, receive, send):
        if scope["method"] == "POST":
            authorization = dict(scope["headers"]).get(b"authorization")
            post_authorizations.append(authorization.decode() if authorization else None)
        body, more_body = b"", True
        while more_body:
            message = await receive()
            body += message.get("body", b"")
            more_body = message.get("more_body", False)
        answer_with = respond(scope["method"], json.loads(body) if body else {})
        if answer_with is None:
            # The body is read, so this returns once the client disconnects.
            await receive()
            return
        status, answer = answer_with
        headers = [(b"content-type", b"application/json"), (b"mcp-session-id", b"session-1")]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        payload = json.dumps(answer).encode() if answer is not None else b""
        await send({"type": "http.response.body", "body": payload})

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{listener.getsockname()[1]}", post_authorizations
    finally:
        server.should_exit = True
        await serving


def _always(status: int) -> Responder:
    # A JSON body that is not a JSON-RPC error, like an auth proxy's 401.
    return lambda http_method, request: (status, {"error": "invalid_token"})


def _legacy_server_whose_tool_call_fails(
    http_method: str, request: dict
) -> tuple[int, dict | None]:
    """A handshake-era server: it refuses the server/discover probe with a 400, then
    answers tools/call with a JSON-RPC internal error over HTTP 200."""
    if http_method != "POST":
        return 405, None
    if request.get("method") == "server/discover":
        return 400, {"error": "unknown method"}
    if "id" not in request:
        return 202, None
    if request["method"] == "initialize":
        result = {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "legacy", "version": "1.0"},
        }
        return 200, {"jsonrpc": "2.0", "id": request["id"], "result": result}
    error = {"code": INTERNAL_ERROR, "message": "tool crashed"}
    return 200, {"jsonrpc": "2.0", "id": request["id"], "error": error}


def _legacy_server_too_slow_to_initialize(
    http_method: str, request: dict
) -> tuple[int, dict | None] | None:
    if request.get("method") == "server/discover":
        return 400, {"error": "unknown method"}
    return None


def _tool_data(url: str) -> McpToolData:
    return McpToolData(
        transport=url, tool_name="search", auth=seal(_SECRET_TOKEN), timeout=5, init_timeout=5
    )


async def _run(operation: str, data: McpToolData) -> str:
    gateway = McpToolGateway(
        FastMCPClientFactory(agent_cryptographer()), agent_cryptographer(), describe_cache_ttl_s=300
    )
    with pytest.raises(McpToolError) as error_info:
        if operation == "describe":
            await gateway.describe(data)
        else:
            await gateway.call(data, {})
    return str(error_info.value)


@pytest.mark.parametrize(
    ("status", "operation", "expected"),
    [
        (
            401,
            "describe",
            "MCP server unreachable for tool_name=search: "
            "Server returned an error response (HTTP 401 Unauthorized)",
        ),
        (
            401,
            "call",
            "MCP call failed for tool_name=search: "
            "Server returned an error response (HTTP 401 Unauthorized)",
        ),
        (
            503,
            "describe",
            "MCP server unreachable for tool_name=search: "
            "Server returned an error response (HTTP 503 Service Unavailable)",
        ),
        (
            503,
            "call",
            "MCP call failed for tool_name=search: "
            "Server returned an error response (HTTP 503 Service Unavailable)",
        ),
    ],
    ids=["401-describe", "401-call", "503-describe", "503-call"],
)
async def test_streamable_http_error_names_the_http_status(status, operation, expected):
    async with _http_server(_always(status)) as (base_url, _):
        message = await _run(operation, _tool_data(f"{base_url}/mcp"))

    assert message == expected


async def test_an_earlier_refused_request_is_not_blamed_for_a_later_error():
    async with _http_server(_legacy_server_whose_tool_call_fails) as (base_url, _):
        message = await _run("call", _tool_data(f"{base_url}/mcp"))

    assert message == "MCP call failed for tool_name=search: tool crashed"


async def test_the_bearer_token_reaches_the_server_on_every_mcp_post():
    async with _http_server(_legacy_server_whose_tool_call_fails) as (base_url, authorizations):
        await _run("call", _tool_data(f"{base_url}/mcp"))

    assert set(authorizations) == {f"Bearer {_SECRET_TOKEN}"}


async def test_a_refused_probe_is_not_blamed_for_a_later_timeout():
    async with _http_server(_legacy_server_too_slow_to_initialize) as (base_url, _):
        data = _tool_data(f"{base_url}/mcp").model_copy(update={"init_timeout": 0.5})
        message = await _run("describe", data)

    assert message.startswith("MCP server unreachable for tool_name=search: ")
    assert "HTTP 400" not in message


async def test_sse_error_names_the_http_status_without_the_appended_one():
    async with _http_server(_always(401)) as (base_url, _):
        message = await _run("describe", _tool_data(f"{base_url}/sse"))

    assert "'401 Unauthorized'" in message
    assert "(HTTP 401" not in message
    assert _SECRET_TOKEN not in message
