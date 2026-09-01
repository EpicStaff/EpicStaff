from rest_framework.views import exception_handler
from rest_framework.exceptions import APIException, NotFound
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from django_app.settings import DEBUG
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse


def custom_exception_handler(exc, context):
    """
    Custom exception handler for API.

    This function handles exceptions raised during the processing of API requests.
    - If the exception is an instance of `APIException`, it customizes the response data
      to include `status_code`, `code`, and a detailed error message.

    - If `DEBUG` is enabled, the default behavior of `exception_handler` is used.

    """

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
