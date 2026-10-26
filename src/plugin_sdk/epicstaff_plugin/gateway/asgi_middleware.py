"""ASGI middleware that refuses every request without a valid gateway context."""

import json
import logging

from epicstaff_plugin.asgi import ASGIApp, Receive, Scope, Send
from epicstaff_plugin.contracts.gateway_context import CONTEXT_HEADER
from epicstaff_plugin.gateway.context_verifier import ContextRejected, ContextVerifier
from epicstaff_plugin.gateway.scope import CONTEXT_SCOPE_KEY
from epicstaff_plugin.runtime.runtime_config import runtime_config

logger = logging.getLogger(__name__)

_CONTEXT_HEADER_NAME = CONTEXT_HEADER.lower().encode("latin-1")
_REFUSAL_STATUS = 401
_REFUSAL_BODY = json.dumps({"code": "context_invalid"}, separators=(",", ":")).encode("utf-8")
_REFUSAL_HEADERS = [
    (b"content-type", b"application/json"),
    (b"content-length", str(len(_REFUSAL_BODY)).encode("latin-1")),
]
# Close code "policy violation"; a server without the denial-response extension turns a
# close before accept into an HTTP 403.
_WEBSOCKET_POLICY_VIOLATION = 1008
_DENIAL_RESPONSE_EXTENSION = "websocket.http.response"


class EpicStaffContextMiddleware:
    """Let an HTTP or WebSocket request reach the app only with a verified gateway context.

    A refused HTTP request is answered `401 {"code": "context_invalid"}`; a refused WebSocket
    handshake gets the same response where the server supports the denial-response
    extension, and is closed with code 1008 otherwise. The verified context is put in the
    scope, where `epicstaff_plugin.gateway.context_from_scope` finds it. Lifespan events pass
    through untouched.

    The plugin's port is reachable by every other plugin on the node, so no request may skip
    this check; `python -m epicstaff_plugin.serve` always installs it.
    """

    def __init__(self, app: ASGIApp, verifier: ContextVerifier | None = None):
        self._app = app
        self._verifier = verifier or ContextVerifier(runtime_config())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        # A WebSocket handshake is a GET, and the gateway signs it as one.
        method = scope["method"] if scope["type"] == "http" else "GET"
        path = scope["path"]
        try:
            token = _context_token(scope["headers"])
            context = await self._verifier.verify_async(token, method, path)
        except ContextRejected as rejection:
            logger.warning("Refused %s %r: gateway context %s", method, path, rejection.reason)
            await _refuse(scope, receive, send)
            return
        await self._app({**scope, CONTEXT_SCOPE_KEY: context}, receive, send)


def _context_token(headers: list[tuple[bytes, bytes]]) -> str:
    values = [value for name, value in headers if name.lower() == _CONTEXT_HEADER_NAME]
    if not values:
        raise ContextRejected("missing")
    if len(values) > 1:
        raise ContextRejected("ambiguous")
    return values[0].decode("latin-1")


async def _refuse(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "http":
        await send(
            {"type": "http.response.start", "status": _REFUSAL_STATUS, "headers": _REFUSAL_HEADERS}
        )
        await send({"type": "http.response.body", "body": _REFUSAL_BODY})
        return
    # The server delivers websocket.connect first; the handshake is answered after it.
    await receive()
    if _DENIAL_RESPONSE_EXTENSION in scope.get("extensions", {}):
        await send(
            {
                "type": "websocket.http.response.start",
                "status": _REFUSAL_STATUS,
                "headers": _REFUSAL_HEADERS,
            }
        )
        await send({"type": "websocket.http.response.body", "body": _REFUSAL_BODY})
        return
    await send({"type": "websocket.close", "code": _WEBSOCKET_POLICY_VIOLATION})
