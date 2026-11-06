"""Plumbing for endpoints served as raw ASGI apps, outside Django's handler and middleware.

A raw app reads the request body straight from `receive`, so a large upload streams
instead of being spooled by Django first. It still authenticates, authorizes and
throttles through a DRF view, and answers in the project's JSON error envelope.
"""

import io
import json
from urllib.parse import parse_qsl

from asgiref.sync import ThreadSensitiveContext, sync_to_async
from django.conf import settings
from django.core import signals
from django.core.handlers.asgi import ASGIHandler, ASGIRequest
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSetMixin
from utils.exception_handler import custom_exception_handler


class ClientDisconnectedError(Exception):
    """The client went away mid-upload; nothing is left to answer."""


async def serve_like_asgi_handler(serve, scope, receive, send) -> None:
    """Run `serve` as ASGIHandler runs a request: in its own sync thread, between the signals.

    `request_finished` closes the database connections the request used.
    """
    async with ThreadSensitiveContext():
        await signals.request_started.asend(sender=ASGIHandler, scope=scope)
        try:
            await serve(scope, receive, send)
        finally:
            await signals.request_finished.asend(sender=ASGIHandler)


def reject_non_utf8_query(scope) -> None:
    """400 for a non-UTF-8 query string, which would crash ASGIRequest or corrupt a value."""
    try:
        parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError({"query": "Query string must be UTF-8, percent-encoded."}) from exc


def authorize_request(view: ViewSetMixin, scope, action: str) -> Request:
    """Authenticate, authorize and throttle the request as `view`'s `action` would be.

    The request is built with an empty body: the real one is read from `receive` later.
    Call it in a sync thread; the authenticated user is cached on the returned request.

    Raises:
        NotAuthenticated, AuthenticationFailed: 401, or 403 when the authenticators
            send no WWW-Authenticate header, as APIView.handle_exception decides.
        PermissionDenied: `view`'s permission classes refuse the request.
        Throttled: `view`'s throttles refuse the request.
    """
    view.action_map = {"post": action}
    view.args, view.kwargs = (), {}
    request = view.initialize_request(ASGIRequest(scope, io.BytesIO()))
    view.request = request
    try:
        view.perform_authentication(request)
        view.check_permissions(request)
        view.check_throttles(request)
    except (NotAuthenticated, AuthenticationFailed) as exc:
        if auth_header := view.get_authenticate_header(request):
            exc.auth_header = auth_header
        else:
            exc.status_code = status.HTTP_403_FORBIDDEN
        raise
    return request


def declared_size(request: Request) -> int | None:
    """Body size from Content-Length, if the client sent one."""
    content_length = request.META.get("CONTENT_LENGTH")
    return int(content_length) if content_length and content_length.isdigit() else None


async def request_body_chunks(receive):
    """Yield the request body chunk by chunk as the ASGI server receives it.

    Raises:
        ClientDisconnectedError: The client left before the body was complete.
    """
    # Each await receive() returns the next ASGI event:
    # - http.request carries a body chunk; more_body=False means the body is complete;
    # - http.disconnect means the client left.
    while True:
        event = await receive()
        if event["type"] == "http.disconnect":
            raise ClientDisconnectedError()
        if event["type"] == "http.request":
            if chunk := event.get("body", b""):
                yield chunk
            if not event.get("more_body", False):
                return


def _header(scope, name: bytes) -> str | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == name:
            return raw_value.decode("latin1")
    return None


def _cors_headers(scope) -> list[tuple[bytes, bytes]]:
    """The CORS headers corsheaders would add, since a raw app bypasses Django."""
    origin = _header(scope, b"origin")
    if not origin:
        return []
    allowed = getattr(settings, "CORS_ALLOWED_ORIGINS", None) or []
    if not (getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False) or origin in allowed):
        return []
    headers = [
        (b"access-control-allow-origin", origin.encode("latin1")),
        (b"vary", b"Origin"),
    ]
    if getattr(settings, "CORS_ALLOW_CREDENTIALS", False):
        headers.append((b"access-control-allow-credentials", b"true"))
    return headers


async def send_json(
    send, scope, status_code: int, payload: dict, extra_headers: dict[str, str] | None = None
) -> None:
    body = json.dumps(payload).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        *_cors_headers(scope),
        *(
            (name.lower().encode("latin1"), value.encode("latin1"))
            for name, value in (extra_headers or {}).items()
        ),
    ]
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def send_error(send, scope, exc: Exception) -> None:
    """Answer with what custom_exception_handler renders for `exc`; re-raise if it renders none."""
    response = await sync_to_async(custom_exception_handler)(exc, {})
    if response is None:
        raise exc
    payload = response.data if isinstance(response, Response) else json.loads(response.content)
    # send_json sets its own Content-Type (and Content-Length).
    headers = {name: value for name, value in response.items() if name.lower() != "content-type"}
    await send_json(send, scope, response.status_code, payload, headers)
