import io
import json
import logging
from urllib.parse import parse_qsl

from asgiref.sync import ThreadSensitiveContext, sync_to_async
from django.conf import settings
from django.core import signals
from django.core.handlers.asgi import ASGIHandler, ASGIRequest
from rest_framework.exceptions import (
    APIException,
    MethodNotAllowed,
    ValidationError,
)
from rest_framework.request import Request

# Reused so this endpoint renders errors exactly like every DRF view in the
# project; duplicating the flattening would let the two envelopes drift apart.
from utils.exception_handler import _flatten_detail

from tables.exceptions import UploadFailedError
from tables.services.storage_service import upload_stream_service
from tables.services.storage_service.archive_formats import is_archive_name
from tables.views.storage_views import StorageAPIView

logger = logging.getLogger(__name__)

UPLOAD_STREAM_ACTION = "upload_stream"


class ClientDisconnectedError(Exception):
    """The browser went away mid-upload; nothing is left to answer."""


async def upload_stream_app(scope, receive, send) -> None:
    """ASGI app for POST /api/storage/upload/stream (routed here from asgi.py).

    Wraps the upload the way Django's ASGIHandler wraps any view: its own sync
    thread (so its own DB connection) and the request_started/finished signals
    that close stale connections."""
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
        request, org_id = await sync_to_async(_check_access)(scope)

        path = request.query_params.get("path", "")
        filename = request.query_params.get("filename", "")
        if not filename:
            raise ValidationError({"filename": "Query param 'filename' is required."})

        chunks = _request_body_chunks(receive)
        if is_archive_name(filename):
            result = await upload_stream_service.upload_archive(org_id, path, filename, chunks)
        else:
            result = await upload_stream_service.upload_file(
                org_id, path, filename, chunks, _declared_size(request)
            )

        await _send_json(send, scope, 200, {"status": "DONE", **result})

    except APIException as exc:
        await _send_error(send, scope, exc)
    except ClientDisconnectedError:
        logger.info("Streaming upload aborted: client disconnected")
    except Exception:
        logger.exception("Streaming upload failed")
        await _send_error(send, scope, UploadFailedError())


def _reject_non_utf8_query(scope) -> None:
    """400 for a query string that is not UTF-8: raw bytes would crash ASGIRequest,
    and a bad %XX escape would silently become U+FFFD in the stored file name."""
    try:
        parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError({"query": "Query string must be UTF-8, percent-encoded."}) from exc


def _check_access(scope) -> tuple[Request, int]:
    """Authenticate and authorize exactly as StorageAPIView would (its authenticators,
    permission classes and rbac_action_map); returns the request and the active org id.

    The view is assembled the way ViewSet.as_view() does it; only the handler
    body is skipped, since the upload never goes through Django."""
    view = StorageAPIView()
    view.action_map = {"post": UPLOAD_STREAM_ACTION}
    view.args, view.kwargs = (), {}
    # Empty body: the real one is read straight from `receive`.
    request = view.initialize_request(ASGIRequest(scope, io.BytesIO()))
    view.request = request
    view.perform_authentication(request)
    view.check_permissions(request)
    view.check_throttles(request)
    return request, view.get_active_org_id()


def _declared_size(request: Request) -> int | None:
    """Body size from Content-Length, if the client sent one."""
    content_length = request.META.get("CONTENT_LENGTH")
    return int(content_length) if content_length and content_length.isdigit() else None


async def _request_body_chunks(receive):
    """Yield the request body chunk by chunk as the ASGI server receives it."""
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
    """The CORS headers corsheaders would have added; skipping Django skips it too,
    and without them a cross-origin frontend (ng serve) can't read the answer."""
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


async def _send_json(send, scope, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        *_cors_headers(scope),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _send_error(send, scope, exc: APIException) -> None:
    """Answer with the project's {status_code, code, message} error envelope."""
    detail = exc.detail if exc.detail else exc.default_detail
    payload = {
        "status_code": exc.status_code,
        "code": exc.default_code,
        "message": _flatten_detail(detail),
    }
    await _send_json(send, scope, exc.status_code, payload)
