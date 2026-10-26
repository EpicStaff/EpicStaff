from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.utils.log import log_response
from django_app.settings import DEBUG
from foundation.transport.http.errors import (
    ClientConnectionError,
    ClientError,
    ClientNotFoundError,
    ClientRateLimitError,
    ClientValidationError,
)
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, Throttled, ValidationError
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler
from tables.clients.errors import ClientError as OutboundClientError

from utils.logger import logger

# Keys DRF generates itself; naming them back at the client adds no information.
_UNLABELLED_KEYS = frozenset({api_settings.NON_FIELD_ERRORS_KEY, "detail"})


def _flatten_detail(detail) -> str:
    """Render DRF's nested error detail as plain text, one message per error."""
    if isinstance(detail, dict):
        return "; ".join(
            _flatten_detail(value)
            if key in _UNLABELLED_KEYS
            else f"{key}: {_flatten_detail(value)}"
            for key, value in detail.items()
        )

    if isinstance(detail, (list, tuple)):
        return "; ".join(_flatten_detail(item) for item in detail)

    return str(detail)


def _upstream_detail(exc: ClientError) -> str | None:
    """Return the upstream response body, or the exception text when there is no body.

    `ClientTimeoutError` is raised without a response, and a response body can be empty,
    so neither is assumed to be there. `None` lets DRF fall back to its default detail
    rather than render an empty message.
    """
    response = getattr(exc, "response", None)
    if response is not None and response.text:
        return response.text
    return str(exc) or None


def _client_error_as_api_exception(exc: ClientError) -> APIException:
    """Translate a transport error from a proxied microservice into a DRF exception.

    Only a missing resource, a rejected payload and rate limiting describe the caller's
    own request, so those statuses pass through. A dependency that could not be reached
    at all is service unavailable, which tells the caller the request is worth retrying.
    Every other upstream failure - timeout, upstream auth, conflict, 5xx - is a failure
    of this gateway's dependency rather than anything the caller did, and is reported as
    a bad gateway: passing an upstream 401 or 409 through would tell the caller something
    false about their own request.
    """
    detail = _upstream_detail(exc)

    if isinstance(exc, ClientNotFoundError):
        return NotFound(detail)
    if isinstance(exc, ClientValidationError):
        return ValidationError(detail)
    if isinstance(exc, ClientRateLimitError):
        return Throttled(detail=detail)
    if isinstance(exc, ClientConnectionError):
        unreachable_error = APIException(detail)
        unreachable_error.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        unreachable_error.default_code = "upstream_service_unreachable"
        return unreachable_error

    upstream_error = APIException(detail)
    upstream_error.status_code = status.HTTP_502_BAD_GATEWAY
    upstream_error.default_code = "upstream_service_error"
    return upstream_error


def _outbound_client_error_as_api_exception(exc: OutboundClientError) -> APIException:
    """Translate an error of an outbound service client (`tables.clients`) into a DRF exception.

    The status code is the client error's own. The message is the error class's
    static `public_detail`: `detail` can carry the upstream response body, which
    goes to the server log only.
    """
    logger.warning(
        "Outbound service call failed: {error_type}: {detail}",
        error_type=type(exc).__name__,
        detail=exc.detail,
    )
    api_exception = APIException(exc.public_detail)
    api_exception.status_code = exc.status_code
    api_exception.default_code = exc.code
    return api_exception


def _log_unhandled_exception(exc: Exception, request, response) -> None:
    """Log the traceback of an exception answered with the generic 500.

    Returning a response stops DRF from re-raising, so Django would log only
    the status line. Django's own request logger records it with the
    traceback, and marks the response as logged so that line is not repeated.
    It goes through stdlib logging rather than the loguru sink on purpose: the
    sink keeps loguru's `diagnose` on, which prints every local variable of
    every frame -- secrets and request payloads included -- and an unhandled
    exception can come from any code path.
    """
    path = request.path if request is not None else "unknown path"
    log_response(
        "Internal Server Error: %s",
        path,
        response=response,
        request=request,
        exception=exc,
    )


def custom_exception_handler(exc, context):
    """Render every exception as the project's `{status_code, code, message}` envelope."""

    # DRF's own `exception_handler()` converts Django's `Http404`/
    # `PermissionDenied` into `NotFound`/`PermissionDenied` APIExceptions,
    # but only on its own local `exc` binding -- the caller's `exc` here is
    # left untouched. Without mirroring that conversion, the `isinstance`
    # check below always misses for these two (e.g. `get_object_or_404()`
    # on a queryset the caller isn't allowed to see), and a correct 404/403
    # response falls through to the generic 500 branch.
    if isinstance(exc, Http404):
        exc = NotFound(*exc.args)
    elif isinstance(exc, PermissionDenied):
        exc = DRFPermissionDenied(*exc.args)
    elif isinstance(exc, ClientError):
        exc = _client_error_as_api_exception(exc)
    elif isinstance(exc, OutboundClientError):
        exc = _outbound_client_error_as_api_exception(exc)

    response = exception_handler(exc, context)

    if isinstance(exc, APIException):
        detail = exc.detail if exc.detail else exc.default_detail
        response.data = {
            "status_code": exc.status_code,
            "code": exc.default_code,
            "message": _flatten_detail(detail),
        }
        errors = getattr(exc, "errors", None)
        if isinstance(errors, list):
            response.data["errors"] = errors
        for name, value in getattr(exc, "headers", {}).items():
            response[name] = value
        extra_response_data = getattr(exc, "extra_response_data", None)
        if isinstance(extra_response_data, dict):
            # Extra keys never replace the envelope's own.
            response.data = {**extra_response_data, **response.data}
        return response

    if not DEBUG:
        # The client gets a generic message: the exception text can carry
        # internals such as database driver errors.
        response = JsonResponse(
            {
                "status_code": 500,
                "code": exc.__class__.__name__,
                "message": "Unpredictable error",
            },
            status=500,
        )
        _log_unhandled_exception(exc, context.get("request"), response)
        return response

    return response
