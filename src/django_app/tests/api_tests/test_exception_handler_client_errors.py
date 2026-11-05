import json

import httpx
import pytest
from foundation.transport.http import errors

from utils.exception_handler import custom_exception_handler


def _status_error(error_type, status_code, body):
    """Build the error exactly as `foundation.transport.http.Client` raises it."""
    return error_type(body, response=httpx.Response(status_code, text=body))


def test_upstream_not_found_renders_as_404_with_the_upstream_body():
    exc = _status_error(errors.ClientNotFoundError, 404, "Venv 42 does not exist.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == 404
    assert response.data == {
        "status_code": 404,
        "code": "not_found",
        "message": "Venv 42 does not exist.",
    }


def test_upstream_validation_error_renders_as_400_with_the_upstream_body():
    exc = _status_error(errors.ClientValidationError, 422, "libraries: must not be empty")

    response = custom_exception_handler(exc, {})

    assert response.status_code == 400
    assert response.data == {
        "status_code": 400,
        "code": "invalid",
        "message": "libraries: must not be empty",
    }


def test_upstream_rate_limit_renders_as_429_with_the_upstream_body():
    exc = _status_error(errors.ClientRateLimitError, 429, "Too many venv builds.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == 429
    assert response.data == {
        "status_code": 429,
        "code": "throttled",
        "message": "Too many venv builds.",
    }


@pytest.mark.parametrize(
    "error_type,status_code",
    [
        (errors.ClientUnauthorizedError, 401),
        (errors.ClientForbiddenError, 403),
        (errors.ClientMethodNotAllowedError, 405),
        (errors.ClientConflictError, 409),
        (errors.ClientServerError, 500),
        (errors.ClientNotImplementedError, 501),
        (errors.ClientBadGatewayError, 502),
        (errors.ClientUnavailableError, 503),
        (errors.ClientGatewayTimeoutError, 504),
        (errors.ClientHTTPStatusError, 418),
    ],
)
def test_other_upstream_failures_render_as_502_with_the_upstream_body(error_type, status_code):
    exc = _status_error(error_type, status_code, "Sandbox said no.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == 502
    assert response.data == {
        "status_code": 502,
        "code": "upstream_service_error",
        "message": "Sandbox said no.",
    }


def test_upstream_error_envelope_is_unwrapped_into_its_message():
    body = json.dumps(
        {
            "type": "client_error",
            "errors": [
                {
                    "code": "conflict",
                    "detail": "CustomLibrary(id=3) is still used by a venv.",
                    "attr": None,
                }
            ],
        }
    )
    exc = _status_error(errors.ClientConflictError, 409, body)

    response = custom_exception_handler(exc, {})

    assert response.data["message"] == "CustomLibrary(id=3) is still used by a venv."


def test_several_upstream_errors_are_joined():
    body = json.dumps(
        {
            "type": "client_error",
            "errors": [
                {"code": "validation_error", "detail": "name: must not be empty", "attr": "name"},
                {"code": "validation_error", "detail": "libs: must be a list", "attr": "libs"},
            ],
        }
    )
    exc = _status_error(errors.ClientValidationError, 400, body)

    response = custom_exception_handler(exc, {})

    assert response.data["message"] == "name: must not be empty; libs: must be a list"


def test_upstream_body_that_is_not_the_envelope_is_passed_through():
    exc = _status_error(errors.ClientNotFoundError, 404, "Venv 42 does not exist.")

    response = custom_exception_handler(exc, {})

    assert response.data["message"] == "Venv 42 does not exist."


def test_unreachable_dependency_renders_as_503():
    exc = errors.ClientConnectionError("The service could not be reached.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == 503
    assert response.data == {
        "status_code": 503,
        "code": "upstream_service_unreachable",
        "message": "The service could not be reached.",
    }


def test_unreachable_dependency_without_a_message_falls_back_to_the_default():
    response = custom_exception_handler(errors.ClientConnectionError(), {})

    assert response.status_code == 503
    assert response.data["message"] == "A server error occurred."


def test_timeout_without_a_response_renders_as_502():
    response = custom_exception_handler(errors.ClientTimeoutError(), {})

    assert response.status_code == 502
    assert response.data == {
        "status_code": 502,
        "code": "upstream_service_error",
        "message": "A server error occurred.",
    }


def test_timeout_message_reaches_the_envelope():
    response = custom_exception_handler(errors.ClientTimeoutError("Read timed out."), {})

    assert response.status_code == 502
    assert response.data["message"] == "Read timed out."


@pytest.mark.parametrize(
    "error_type,status_code,expected_status,expected_message",
    [
        (errors.ClientNotFoundError, 404, 404, "Not found."),
        (errors.ClientValidationError, 400, 400, "Invalid input."),
        (errors.ClientRateLimitError, 429, 429, "Request was throttled."),
        (errors.ClientServerError, 500, 502, "A server error occurred."),
    ],
)
def test_empty_upstream_body_falls_back_to_the_default_message(
    error_type, status_code, expected_status, expected_message
):
    exc = _status_error(error_type, status_code, "")

    response = custom_exception_handler(exc, {})

    assert response.status_code == expected_status
    assert response.data["message"] == expected_message
