
from rest_framework.views import exception_handler
from rest_framework.exceptions import APIException, ValidationError
from django_app.settings import DEBUG
from django.http import JsonResponse


MESSAGE_PATTERN = "{error_name}: {error_detail}"


def custom_exception_handler(exc, context):
    """
    Custom exception handler for API.

    This function handles exceptions raised during the processing of API requests.
    - If the exception is an instance of `APIException`, it customizes the response data
      to include `status_code`, `code`, and a detailed error message.

    - If `DEBUG` is enabled, the default behavior of `exception_handler` is used.

    """

    response = exception_handler(exc, context)
    if isinstance(exc, APIException):
        error_data = {
            "status_code": exc.status_code,
            "code": exc.default_code,
            "message": MESSAGE_PATTERN.format(
                error_name=type(exc).__name__,
                error_detail=exc.args[0] if exc.args else exc.detail or exc.default_detail
            ),
        }

        if (errors := getattr(exc, 'errors', None)) is not None:
            error_data["errors"] = errors

        elif errors is None and isinstance(exc, ValidationError):
            if isinstance(exc.detail, dict):
                detail = [exc.detail]
            elif isinstance(exc.detail, list) and exc.detail and isinstance(exc.detail[0], dict):
                detail = exc.detail
            else:
                detail = [{None: exc.detail}]

            errors = [
                {
                    "field": field,
                    "value": None,
                    "reason": "; ".join(reason if isinstance(reason, list) else [reason])
                }
                for data in detail
                for field, reason in data.items()
            ]

            error_data["errors"] = errors

        response.data = error_data
        return response

    if not DEBUG:
        response = {
            "status_code": 500,
            "code": exc.__class__.__name__,
            "message": f"{exc.__class__.__name__}: Unpredictable error",
        }
        return JsonResponse(response)

    return response
