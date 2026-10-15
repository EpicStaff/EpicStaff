from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django_app.settings import DEBUG
from foundation.transport.http.errors import (
    ClientError,
    ClientNotFoundError,
    ClientRateLimitError,
    ClientValidationError,
)
from rest_framework import exceptions, status
from rest_framework.exceptions import APIException
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler

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
    own request, so those statuses pass through. Every other upstream failure - timeout,
    upstream auth, conflict, 5xx - is a failure of this gateway's dependency rather than
    anything the caller did, and is reported as a bad gateway: passing an upstream 401 or
    409 through would tell the caller something false about their own request.
    """
    detail = _upstream_detail(exc)

    if isinstance(exc, ClientNotFoundError):
        return exceptions.NotFound(detail)
    if isinstance(exc, ClientValidationError):
        return exceptions.ValidationError(detail)
    if isinstance(exc, ClientRateLimitError):
        return exceptions.Throttled(detail=detail)

    upstream_error = APIException(detail)
    upstream_error.status_code = status.HTTP_502_BAD_GATEWAY
    upstream_error.default_code = "upstream_service_error"
    return upstream_error


def custom_exception_handler(exc, context):
    """Render every exception as the project's `{status_code, code, message}` envelope."""

    if isinstance(exc, Http404):
        exc = exceptions.NotFound(*exc.args)
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied(*exc.args)
    elif isinstance(exc, ClientError):
        exc = _client_error_as_api_exception(exc)

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
        return JsonResponse(
            {
                "status_code": 500,
                "code": exc.__class__.__name__,
                "message": "Unpredictable error",
            },
            status=500,
        )

    return response
