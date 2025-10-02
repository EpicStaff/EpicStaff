from rest_framework.views import exception_handler
from rest_framework.exceptions import APIException
from django_app.settings import DEBUG
from django.http import JsonResponse


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

        response.data = {
            "status_code": exc.status_code,
            "code": exc.default_code,
            "message": (
                f"{exc.__class__.__name__}: {exc.args[0]}"
                if exc.args
                else f"{exc.__class__.__name__}: {exc.detail or exc.default_detail}"
            ),
        }
        return response

    if not DEBUG:
        response = {
            "status_code": 500,
            "code": exc.__class__.__name__,
            "message": f"{exc.__class__.__name__}: Unpredictable error",
        }
        return JsonResponse(response)

    return response
