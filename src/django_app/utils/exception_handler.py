from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django_app.settings import DEBUG
from rest_framework.exceptions import APIException, NotFound
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
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
