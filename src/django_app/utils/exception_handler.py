from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import exceptions
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler

from django_app.settings import DEBUG


def custom_exception_handler(exc, context):
    """Render every exception as the project's `{status_code, code, message}` envelope."""

    if isinstance(exc, Http404):
        exc = exceptions.NotFound(*exc.args)
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied(*exc.args)

    response = exception_handler(exc, context)

    if isinstance(exc, APIException):
        response.data = {
            "status_code": exc.status_code,
            "code": exc.default_code,
            "message": (
                f"{exc.__class__.__name__}: {exc.args[0]}"
                if exc.args
                else f"{exc.__class__.__name__}: {exc.detail or exc.default_detail}"
            ),
        }
        errors = getattr(exc, "errors", None)
        if isinstance(errors, list):
            response.data["errors"] = errors
        return response

    if not DEBUG:
        return JsonResponse(
            {
                "status_code": 500,
                "code": exc.__class__.__name__,
                "message": f"{exc.__class__.__name__}: Unpredictable error",
            },
            status=500,
        )

    return response
