import json

import httpx
import pytest
from foundation.transport.http import errors
from loguru import logger

from utils.exception_handler import custom_exception_handler

UPSTREAM_TEXT = "Traceback: /srv/sandbox/venvs/42 is owned by root"


def _status_error(error_type, status_code, body):
    """Build the error exactly as `foundation.transport.http.Client` raises it."""
    return error_type(body, response=httpx.Response(status_code, text=body))


def _envelope(*items):
    return json.dumps({"type": "client_error", "errors": list(items)})


@pytest.fixture
def logged():
    lines: list[str] = []
    sink_id = logger.add(lines.append, level="WARNING", format="{message}")
    yield lines
    logger.remove(sink_id)


def _only_item(response) -> dict:
    [item] = response.data["errors"]
    return item


def test_an_upstream_conflict_in_the_envelope_is_passed_through_as_it_is():
    body = _envelope(
        {
            "code": "conflict",
            "detail": "CustomLibrary(id=3) is still used by a venv.",
            "attr": None,
        }
    )

    response = custom_exception_handler(_status_error(errors.ClientConflictError, 409, body), {})

    assert response.status_code == 409
    assert response.data == {
        "type": "client_error",
        "errors": [
            {
                "code": "conflict",
                "detail": "CustomLibrary(id=3) is still used by a venv.",
                "attr": None,
                "context": None,
            }
        ],
    }


def test_every_upstream_item_keeps_its_code_and_attr_and_the_status_is_kept():
    body = _envelope(
        {"code": "string_too_short", "detail": "must not be empty", "attr": "name"},
        {"code": "list_type", "detail": "must be a list", "attr": "libs", "context": {"max": 3}},
    )

    response = custom_exception_handler(_status_error(errors.ClientValidationError, 422, body), {})

    assert response.status_code == 422
    assert [(item["code"], item["attr"], item["context"]) for item in response.data["errors"]] == [
        ("string_too_short", "name", None),
        ("list_type", "libs", {"max": 3}),
    ]


@pytest.mark.parametrize(
    "error_type,status_code,expected_status,expected_code,expected_detail",
    [
        (errors.ClientNotFoundError, 404, 404, "not_found", "Not found."),
        (errors.ClientValidationError, 422, 400, "invalid", "Invalid input."),
        (errors.ClientRateLimitError, 429, 429, "throttled", "Request was throttled."),
    ],
)
def test_an_upstream_refusal_not_in_the_envelope_keeps_its_class_with_a_fixed_text(
    error_type, status_code, expected_status, expected_code, expected_detail, logged
):
    response = custom_exception_handler(_status_error(error_type, status_code, UPSTREAM_TEXT), {})

    assert response.status_code == expected_status
    assert _only_item(response) == {
        "code": expected_code,
        "detail": expected_detail,
        "attr": None,
        "context": None,
    }
    assert UPSTREAM_TEXT in "".join(logged)


@pytest.mark.parametrize(
    "error_type,status_code,code",
    [
        (errors.ClientUnauthorizedError, 401, "unauthorized"),
        (errors.ClientForbiddenError, 403, "forbidden"),
        (errors.ClientMethodNotAllowedError, 405, "method_not_allowed"),
        (errors.ClientConflictError, 409, "conflict"),
        (errors.ClientHTTPStatusError, 423, "locked"),
        (errors.ClientHTTPStatusError, 499, "client_error"),
    ],
)
def test_other_upstream_client_errors_keep_their_status(error_type, status_code, code):
    response = custom_exception_handler(_status_error(error_type, status_code, UPSTREAM_TEXT), {})

    assert response.status_code == status_code
    assert _only_item(response)["code"] == code
    assert UPSTREAM_TEXT not in json.dumps(response.data)


@pytest.mark.parametrize(
    "body",
    [
        "<html><body>Bad request</body></html>",
        json.dumps({"code": "not_found", "detail": "Venv 42 does not exist."}),
        _envelope(),
        json.dumps({"type": "client_error", "errors": [{"code": "x"}]}),
    ],
    ids=["html", "other-json-shape", "envelope-without-errors", "item-without-detail"],
)
def test_an_upstream_body_that_is_not_a_valid_envelope_is_not_passed_through(body):
    response = custom_exception_handler(_status_error(errors.ClientNotFoundError, 404, body), {})

    assert response.status_code == 404
    assert _only_item(response)["detail"] == "Not found."


@pytest.mark.parametrize(
    "error_type,status_code",
    [
        (errors.ClientServerError, 500),
        (errors.ClientNotImplementedError, 501),
        (errors.ClientBadGatewayError, 502),
        (errors.ClientUnavailableError, 503),
        (errors.ClientGatewayTimeoutError, 504),
    ],
)
def test_an_upstream_server_failure_is_a_502_without_the_upstream_body(
    error_type, status_code, logged
):
    server_envelope = json.dumps(
        {"type": "server_error", "errors": [{"code": "unknown", "detail": UPSTREAM_TEXT}]}
    )

    response = custom_exception_handler(
        _status_error(error_type, status_code, server_envelope), {}
    )

    assert response.status_code == 502
    assert response.data == {
        "type": "server_error",
        "errors": [
            {
                "code": "upstream_service_error",
                "detail": "A service this request depends on failed.",
                "attr": None,
                "context": None,
            }
        ],
    }
    assert UPSTREAM_TEXT in "".join(logged)


def test_an_unreachable_dependency_is_a_503():
    response = custom_exception_handler(
        errors.ClientConnectionError("Connection refused to sandbox:8000"), {}
    )

    assert response.status_code == 503
    assert _only_item(response) == {
        "code": "upstream_service_unreachable",
        "detail": "A service this request depends on could not be reached. Try again later.",
        "attr": None,
        "context": None,
    }


def test_a_timeout_without_a_response_is_a_502_with_the_fixed_text():
    response = custom_exception_handler(errors.ClientTimeoutError("Read timed out."), {})

    assert response.status_code == 502
    assert _only_item(response)["detail"] == "A service this request depends on failed."
