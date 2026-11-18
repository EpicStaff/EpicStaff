"""
McpToolGateway errors over real HTTP transports.

A local uvicorn server answers every request from a script, or serves a real FastMCP
app; the gateway uses the real FastMCPClientFactory, so the error text is what an
agent run reports.
"""

from __future__ import annotations

import asyncio
import base64
import json
import socket
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import anyio
import pytest
import uvicorn
from app.exceptions import McpToolError
from app.tools.mcp.client_factory import FastMCPClientFactory
from app.tools.mcp.gateway import McpToolGateway
from fastmcp import FastMCP
from mcp.types import INTERNAL_ERROR
from shared.models.tools import McpToolData

from tests.log_capture import capture_logs_at, log_line_starting_with
from tests.secret_sealing import agent_cryptographer, seal


@dataclass(frozen=True)
class _EventStream:
    """Answer 200 with a text/event-stream, send ``events`` on it, then hold it open."""

    events: str = ""


# Returns (status, json_body), an _EventStream, or None to hold the request until the
# client gives up.
Responder = Callable[[str, dict], tuple[int, dict | None] | _EventStream | None]

_SECRET_TOKEN = "SECRET-BEARER-TOKEN-1357"
_USERINFO_SECRET = "USERINFO-SECRET-2468"
_QUERY_SECRET = "QUERY-SECRET-8642"
_PATH_SECRET = "sk-ak-PATH-SECRET-9753"

_HTTP_TRANSPORTS = pytest.mark.parametrize(
    ("transport", "path"), [("sse", "/sse"), ("http", "/mcp")], ids=["sse", "streamable_http"]
)


@asynccontextmanager
async def _serving(app, lifespan: str = "off"):
    """Serve the ASGI ``app`` on a local port and yield its base URL."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, lifespan=lifespan, log_level="warning"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        await serving


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
        if isinstance(answer_with, _EventStream):
            headers = [(b"content-type", b"text/event-stream")]
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            stream_start = {"body": answer_with.events.encode(), "more_body": True}
            await send({"type": "http.response.body", **stream_start})
        if answer_with is None or isinstance(answer_with, _EventStream):
            # The body is read, so this returns once the client disconnects.
            await receive()
            return
        status, answer = answer_with
        headers = [(b"content-type", b"application/json"), (b"mcp-session-id", b"session-1")]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        payload = json.dumps(answer).encode() if answer is not None else b""
        await send({"type": "http.response.body", "body": payload})

    async with _serving(app) as base_url:
        yield base_url, post_authorizations


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


def _sse_server_refusing_messages(
    http_method: str, request: dict
) -> tuple[int, dict] | _EventStream:
    """Announces a message endpoint relative to the configured URL's own path, so the
    joined URL keeps that path, then refuses every message POSTed there with a 401."""
    if http_method == "GET":
        return _EventStream("event: endpoint\ndata: messages?session_id=abc\n\n")
    return 401, {"error": "invalid_token"}


async def _redirecting_to_a_trailing_slash(scope, receive, send):
    # The same path with a trailing slash, like a framework's slash normalisation. The
    # SDK does not follow a 301 for a POST, which would turn it into a GET.
    location = f"{scope['path']}/".encode()
    await send({"type": "http.response.start", "status": 301, "headers": [(b"location", location)]})
    await send({"type": "http.response.body", "body": b""})


def _server_with_tool(name: str, tool: Callable) -> FastMCP:
    server = FastMCP("stub")
    server.tool(tool, name=name)
    return server


def _lookup(query: str) -> str:
    return query


async def _search_slowly() -> str:
    await asyncio.sleep(1)
    return "done"


def _url_with_secrets(base_url: str, path: str) -> str:
    """The server URL with a password in its userinfo and an API key in its query."""
    with_userinfo = base_url.replace("http://", f"http://agent:{_USERINFO_SECRET}@")
    return f"{with_userinfo}{path}?api_key={_QUERY_SECRET}"


def _assert_no_url_secret(text: str) -> None:
    assert _USERINFO_SECRET not in text
    assert _QUERY_SECRET not in text
    assert _PATH_SECRET not in text


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


@pytest.mark.parametrize(
    ("operation", "path", "prefix"),
    [
        ("describe", "/sse", "MCP server unreachable"),
        ("call", "/sse", "MCP call failed"),
        ("describe", f"/mcp/{_PATH_SECRET}/sse", "MCP server unreachable"),
    ],
    ids=["describe", "call", "secret-in-path"],
)
async def test_sse_status_error_names_the_status_and_only_the_server_origin(
    operation, path, prefix
):
    async with _http_server(_always(401)) as (base_url, _):
        message = await _run(operation, _tool_data(_url_with_secrets(base_url, path)))

    assert message == f"{prefix} for tool_name=search: HTTP 401 Unauthorized from {base_url}"
    _assert_no_url_secret(message)
    assert _SECRET_TOKEN not in message


@_HTTP_TRANSPORTS
async def test_tool_not_found_names_only_the_server_origin(transport, path):
    app = _server_with_tool("lookup", _lookup).http_app(transport=transport, path=path)
    async with _serving(app, lifespan="on") as base_url:
        message = await _run("describe", _tool_data(_url_with_secrets(base_url, path)))

    assert message == f"Tool 'search' not found on MCP server at {base_url}"
    _assert_no_url_secret(message)


async def test_tool_not_found_with_a_quote_in_the_password_names_only_the_server_origin():
    path = f"/mcp/{_PATH_SECRET}/sse"
    app = _server_with_tool("lookup", _lookup).http_app(transport="sse", path=path)
    async with _serving(app, lifespan="on") as base_url:
        with_userinfo = base_url.replace("http://", f"http://agent:pa'ss-{_USERINFO_SECRET}@")
        url = f"{with_userinfo}{path}?api_key={_QUERY_SECRET}"
        message = await _run("describe", _tool_data(url))

    assert message == f"Tool 'search' not found on MCP server at {base_url}"
    _assert_no_url_secret(message)


async def test_sse_sdk_log_line_names_the_refusal_without_url_secrets():
    with capture_logs_at("WARNING") as logs:
        async with _http_server(_sse_server_refusing_messages) as (base_url, _):
            data = _tool_data(_url_with_secrets(base_url, f"/mcp/{_PATH_SECRET}/sse"))
            await _run("describe", data.model_copy(update={"init_timeout": 0.5}))

    refused_post = log_line_starting_with(logs, "Error in post_writer")
    assert refused_post == f"Error in post_writer: HTTP 401 Unauthorized from {base_url}"
    _assert_no_url_secret("".join(logs))


@pytest.mark.parametrize(
    ("operation", "prefix"),
    [("describe", "MCP server unreachable"), ("call", "MCP call failed")],
)
async def test_streamable_http_redirect_names_only_the_target_origin(operation, prefix):
    with capture_logs_at("WARNING") as logs:
        async with _serving(_redirecting_to_a_trailing_slash) as base_url:
            url = _url_with_secrets(base_url, f"/mcp/{_PATH_SECRET}")
            message = await _run(operation, _tool_data(url))

    assert message.startswith(f"{prefix} for tool_name=search: Redirect to {base_url} not followed")
    _assert_no_url_secret(message)
    # The SDK also logs the redirect itself.
    assert any(line.startswith(f"Redirect to {base_url} not followed") for line in logs)
    _assert_no_url_secret("".join(logs))


def _basic(credentials: str) -> str:
    return f"Basic {base64.b64encode(credentials.encode()).decode()}"


@pytest.mark.parametrize(
    ("userinfo", "token", "expected_authorization"),
    [
        ("agent:p%40ss", None, _basic("agent:p@ss")),
        ("token", None, _basic("token:")),
        ("agent:pw", _SECRET_TOKEN, f"Bearer {_SECRET_TOKEN}"),
    ],
    ids=["percent-encoded-password", "user-only", "token-wins-over-userinfo"],
)
async def test_the_server_receives_the_authorization_the_url_and_token_imply(
    userinfo, token, expected_authorization
):
    async with _http_server(_always(401)) as (base_url, authorizations):
        url = base_url.replace("http://", f"http://{userinfo}@") + "/mcp"
        await _run(
            "describe", _tool_data(url).model_copy(update={"auth": seal(token) if token else None})
        )

    assert set(authorizations) == {expected_authorization}


@pytest.mark.parametrize(
    ("operation", "prefix"),
    [("describe", "MCP server unreachable"), ("call", "MCP call failed")],
)
async def test_sse_server_that_never_announces_its_endpoint_fails_within_init_timeout(
    operation, prefix
):
    async with _http_server(lambda http_method, request: _EventStream()) as (base_url, _):
        data = _tool_data(f"{base_url}/sse").model_copy(update={"init_timeout": 0.5})
        # Unbounded, the SDK waits 300 s (its sse_read_timeout) for the endpoint event.
        with anyio.fail_after(5):
            message = await _run(operation, data)

    expected = f"{prefix} for tool_name=search: did not finish connecting within init_timeout=0.5 s"
    assert message == expected


async def test_an_init_timeout_of_zero_means_no_limit():
    app = _server_with_tool("search", _lookup).http_app(transport="sse", path="/sse")
    async with _serving(app, lifespan="on") as base_url:
        data = _tool_data(f"{base_url}/sse").model_copy(update={"init_timeout": 0})
        gateway = McpToolGateway(
            FastMCPClientFactory(agent_cryptographer()),
            agent_cryptographer(),
            describe_cache_ttl_s=300,
        )
        described = await gateway.describe(data)

    assert described.input_schema["required"] == ["query"]


@_HTTP_TRANSPORTS
async def test_a_tool_call_may_run_longer_than_init_timeout(transport, path):
    app = _server_with_tool("search", _search_slowly).http_app(transport=transport, path=path)
    async with _serving(app, lifespan="on") as base_url:
        data = _tool_data(f"{base_url}{path}").model_copy(update={"init_timeout": 0.5})
        gateway = McpToolGateway(
            FastMCPClientFactory(agent_cryptographer()),
            agent_cryptographer(),
            describe_cache_ttl_s=300,
        )
        output = await gateway.call(data, {})

    assert output == '{"result": "done"}'
