import io
import json
from urllib.parse import parse_qsl

from asgiref.sync import ThreadSensitiveContext, sync_to_async
from django.conf import settings
from django.core import signals
from django.core.handlers.asgi import ASGIHandler, ASGIRequest
from rbac.access.asserts import assert_org_permission
from rbac.models.enums import Permission
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    PermissionDenied,
    ValidationError,
)
from rest_framework.request import Request
from rest_framework.response import Response
from tables.exceptions import OverwriteNotPermitted
from tables.services.storage_service import upload as upload_service
from tables.services.storage_service.archive_unpacking.names import is_archive_name
from tables.views.storage_views import StorageAPIView
from utils.exception_handler import custom_exception_handler
from utils.logger import logger

UPLOAD_STREAM_ACTION = "upload_stream"

# Routed by asgi.py, not a URLconf; nginx's template and StorageApiService repeat this literal.
UPLOAD_STREAM_PATH = "/api/storage/upload/stream"


class ClientDisconnectedError(Exception):
    """The browser went away mid-upload; nothing is left to answer."""


async def upload_stream_app(scope, receive, send) -> None:
    """ASGI app for the upload stream, wrapped like ASGIHandler: own sync thread and signals."""
    async with ThreadSensitiveContext():
        await signals.request_started.asend(sender=ASGIHandler, scope=scope)
        try:
            await _serve_upload(scope, receive, send)
        finally:
            await signals.request_finished.asend(sender=ASGIHandler)


async def _serve_upload(scope, receive, send) -> None:
    """Check access, hand the request body to the upload service, answer with JSON."""
    try:
        method = scope.get("method")
        if method != "POST":
            raise MethodNotAllowed(method or "")

        _reject_non_utf8_query(scope)
        # Check auth, permissions (FILES:CREATE) and throttling the same way StorageAPIView does.
        request, org_id = await sync_to_async(_check_access)(scope)

        path = request.query_params.get("path", "")
        filename = request.query_params.get("filename", "")
        if not filename:
            raise ValidationError({"filename": "Query param 'filename' is required."})

        # Only builds the chunk generator: the service reads the body later, after checks and a slot.
        chunks = _request_body_chunks(receive)
        declared_size = _declared_size(request)
        # The file name decides the route: archive or plain file.
        upload = (
            upload_service.upload_archive
            if is_archive_name(filename)
            else upload_service.upload_file
        )
        # A plain file streams straight to storage; an archive is buffered first.
        result = await upload(
            org_id,
            path,
            filename,
            chunks,
            declared_size,
            authorize_overwrite=_overwrite_authorizer(request.user, org_id),
        )

        await _send_json(send, scope, 200, {"status": "DONE", **result})

    except APIException as exc:
        await _send_error(send, scope, exc)
    except ClientDisconnectedError:
        logger.info("Streaming upload aborted: client disconnected")
    except Exception as exc:
        logger.exception("Streaming upload failed")
        await _send_error(send, scope, exc)


def _reject_non_utf8_query(scope) -> None:
    """400 for a non-UTF-8 query string, which would crash ASGIRequest or corrupt the file name."""
    try:
        parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError({"query": "Query string must be UTF-8, percent-encoded."}) from exc


def _check_access(scope) -> tuple[Request, int]:
    """Authenticate and authorize exactly as StorageAPIView would; return the request and org id."""
    view = StorageAPIView()
    view.action_map = {"post": UPLOAD_STREAM_ACTION}
    view.args, view.kwargs = (), {}
    # Empty body: the real one is read straight from `receive`.
    request = view.initialize_request(ASGIRequest(scope, io.BytesIO()))
    view.request = request
    try:
        view.perform_authentication(request)
        view.check_permissions(request)
        view.check_throttles(request)
    except (NotAuthenticated, AuthenticationFailed) as exc:
        # What APIView.handle_exception does before rendering a 401.
        if auth_header := view.get_authenticate_header(request):
            exc.auth_header = auth_header
        else:
            exc.status_code = status.HTTP_403_FORBIDDEN
        raise
    return request, view.get_active_org_id()


def _overwrite_authorizer(user, org_id: int):
    """Build the check run when a file is already at the target: replacing needs UPDATE."""

    def authorize_overwrite() -> None:
        try:
            assert_org_permission(
                user, org_id, StorageAPIView.rbac_resource_type, Permission.UPDATE
            )
        except PermissionDenied as exc:
            raise OverwriteNotPermitted() from exc

    return authorize_overwrite


def _declared_size(request: Request) -> int | None:
    """Body size from Content-Length, if the client sent one."""
    content_length = request.META.get("CONTENT_LENGTH")
    return int(content_length) if content_length and content_length.isdigit() else None


async def _request_body_chunks(receive):
    """Yield the request body chunk by chunk as the ASGI server receives it."""
    # Each await receive() returns the next ASGI event:
    # - http.request carries a body chunk; more_body=False means the body is complete;
    # - http.disconnect means the client left, so raise ClientDisconnectedError.
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
    """The CORS headers corsheaders would add, since this app bypasses Django."""
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


async def _send_json(
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


async def _send_error(send, scope, exc: Exception) -> None:
    """Answer with what custom_exception_handler renders for `exc`; re-raise if it renders none."""
    response = await sync_to_async(custom_exception_handler)(exc, {})
    if response is None:
        raise exc
    payload = response.data if isinstance(response, Response) else json.loads(response.content)
    # _send_json sets its own Content-Type (and Content-Length).
    headers = {name: value for name, value in response.items() if name.lower() != "content-type"}
    await _send_json(send, scope, response.status_code, payload, headers)
