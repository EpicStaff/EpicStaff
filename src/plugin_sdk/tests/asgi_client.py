"""Calling an ASGI app in-process, the way uvicorn would, without a test client dependency."""

import asyncio
import json
from dataclasses import dataclass, field


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body)


@dataclass
class WebSocketOutcome:
    """What the app sent back on a WebSocket handshake."""

    messages: list[dict] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return any(message["type"] == "websocket.accept" for message in self.messages)

    @property
    def denial_status(self) -> int | None:
        start = next(
            (m for m in self.messages if m["type"] == "websocket.http.response.start"), None
        )
        return start["status"] if start else None

    @property
    def close_code(self) -> int | None:
        close = next((m for m in self.messages if m["type"] == "websocket.close"), None)
        return close["code"] if close else None


def _scope(scope_type, method, path, headers, query_string=b""):
    raw_headers = [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers]
    return {
        "type": scope_type,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http" if scope_type == "http" else "ws",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 20001),
        "extensions": {},
        "state": {},
    }


def request(app, method, path, headers=None, body=b"", *, query=""):
    """Send one HTTP request; `headers` is a dict or a list of (name, value) pairs.

    `query` is the raw query string, without the `?`.
    """
    return asyncio.run(send_request(app, method, path, headers, body, query=query))


async def send_request(app, method, path, headers=None, body=b"", *, query=""):
    """`request`, from inside a running event loop (for an app whose resources live in it)."""
    pairs = list(headers.items()) if isinstance(headers, dict) else list(headers or [])
    sent = []
    pending = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if pending:
            return pending.pop(0)
        await asyncio.sleep(3600)

    async def send(message):
        sent.append(message)

    await app(_scope("http", method, path, pairs, query.encode("latin-1")), receive, send)
    start = next(message for message in sent if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    response_headers = {
        name.decode("latin-1"): value.decode("latin-1") for name, value in start.get("headers", [])
    }
    return Response(start["status"], response_headers, response_body)


def websocket(app, path, headers=None, *, denial_response=False):
    """Open a WebSocket and close it straight away; return what the app sent."""
    pairs = list((headers or {}).items())
    scope = _scope("websocket", "GET", path, pairs)
    del scope["method"]
    if denial_response:
        scope["extensions"] = {"websocket.http.response": {}}
    outcome = WebSocketOutcome()

    async def run():
        incoming = [{"type": "websocket.connect"}, {"type": "websocket.disconnect", "code": 1000}]

        async def receive():
            if incoming:
                return incoming.pop(0)
            await asyncio.sleep(3600)

        async def send(message):
            outcome.messages.append(message)

        await app(scope, receive, send)

    asyncio.run(run())
    return outcome


def lifespan(app):
    """Run the app's lifespan startup and shutdown; return the messages it sent."""
    sent = []

    async def run():
        incoming = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

        async def receive():
            return incoming.pop(0)

        async def send(message):
            sent.append(message)

        await app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send)

    asyncio.run(run())
    return sent
