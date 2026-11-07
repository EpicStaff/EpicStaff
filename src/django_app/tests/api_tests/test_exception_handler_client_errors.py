import json
import re

import httpx
import pytest
from foundation.transport.http import errors

from utils.exception_handler import custom_exception_handler
from utils.logger import logger

REFUSED_TEXT = "The request was refused. Check what you entered and try again."
SERVER_FAILURE_PATTERN = (
    r"Something went wrong on the server\. Try again or contact your administrator "
    r"\(reference: ([0-9a-f]{12})\)\."
)
NOT_FOUND_TEXT = "The requested item wasn't found. It may have been deleted."
RATE_LIMITED_TEXT = "Too many requests right now. Wait a moment and try again."


def _status_error(error_type, status_code, body):
    """Build the error exactly as `foundation.transport.http.Client` raises it."""
    return error_type(body, response=httpx.Response(status_code, text=body))


@pytest.fixture
def captured_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING", format="{message}")
    yield records
    logger.remove(sink_id)


def _validation_body(*errors_given: tuple[str, str | None]) -> str:
    """A 400 body as the sandbox's error handler writes it, from (detail, attr) pairs."""
    return json.dumps(
        {
            "type": "validation_error",
            "errors": [
                {"code": "value_error", "detail": detail, "attr": attr}
                for detail, attr in errors_given
            ],
        }
    )


@pytest.mark.parametrize(
    "body,expected_message",
    [
        pytest.param(
            _validation_body(("Value error, version 2.0 is outside >=1.0,<2.0", "libs.0")),
            "libs.0: version 2.0 is outside >=1.0,<2.0.",
            id="one-field-detail",
        ),
        pytest.param(
            _validation_body(("The venv needs at least one library.", None)),
            "The venv needs at least one library.",
            id="detail-of-no-single-field",
        ),
        pytest.param(
            _validation_body(
                ("Value error, version 2.0 is outside >=1.0,<2.0", "libs.0"),
                ("Name must not be empty.", "name"),
                ("Libraries must have different names", None),
            ),
            "libs.0: version 2.0 is outside >=1.0,<2.0. name: Name must not be empty. "
            "Libraries must have different names.",
            id="several-details",
        ),
    ],
)
def test_upstream_validation_error_shows_only_the_detail_texts(body, expected_message):
    exc = _status_error(errors.ClientValidationError, 400, body)

    response = custom_exception_handler(exc, {})

    assert response.status_code == 400
    assert response.data == {
        "status_code": 400,
        "code": "invalid",
        "message": expected_message,
    }


@pytest.mark.parametrize(
    "body",
    [
        "libraries: must not be empty",
        json.dumps({"detail": "libraries: must not be empty"}),
        json.dumps({"type": "validation_error", "errors": [{"code": "missing"}]}),
        json.dumps({"type": "validation_error", "errors": [{"detail": "  "}]}),
        json.dumps(["libraries: must not be empty"]),
    ],
    ids=["plain-text", "no-errors-list", "error-without-detail", "blank-detail", "json-list"],
)
def test_upstream_validation_error_of_an_unexpected_shape_shows_a_generic_message(
    captured_logs, body
):
    exc = _status_error(errors.ClientValidationError, 400, body)

    response = custom_exception_handler(exc, {})

    assert response.status_code == 400
    assert response.data == {
        "status_code": 400,
        "code": "invalid",
        "message": REFUSED_TEXT,
    }
    assert any(body in record for record in captured_logs)


@pytest.mark.parametrize(
    "error_type,status_code,code",
    [
        (errors.ClientMethodNotAllowedError, 405, "method_not_allowed"),
        (errors.ClientConflictError, 409, "conflict"),
        (errors.ClientHTTPStatusError, 423, "locked"),
    ],
)
def test_upstream_client_errors_keep_their_status_and_show_the_detail(
    error_type, status_code, code
):
    exc = _status_error(error_type, status_code, _validation_body(("Sandbox said no.", None)))

    response = custom_exception_handler(exc, {})

    assert response.status_code == status_code
    assert response.data == {
        "status_code": status_code,
        "code": code,
        "message": "Sandbox said no.",
    }


def test_an_upstream_status_outside_the_standard_table_is_still_the_callers():
    exc = _status_error(errors.ClientHTTPStatusError, 499, "Sandbox said no.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == 499
    assert response.data["code"] == "client_error"


def test_upstream_error_envelope_is_unwrapped_into_its_message():
    body = json.dumps(
        {
            "type": "client_error",
            "errors": [
                {
                    "code": "custom_library_in_use",
                    "detail": "CustomLibrary(id=3) is still used by a venv.",
                    "attr": None,
                }
            ],
        }
    )
    exc = _status_error(errors.ClientConflictError, 409, body)

    response = custom_exception_handler(exc, {})

    assert response.data["message"] == "CustomLibrary(id=3) is still used by a venv."


def test_upstream_not_found_shows_its_detail():
    exc = _status_error(
        errors.ClientNotFoundError, 404, _validation_body(("Venv(id=42) not found.", None))
    )

    response = custom_exception_handler(exc, {})

    assert response.status_code == 404
    assert response.data["message"] == "Venv(id=42) not found."


def _cited_reference(response) -> str:
    """The reference a server failure's message cites, checked against the response's own."""
    match = re.fullmatch(SERVER_FAILURE_PATTERN, response.data["message"])
    assert match is not None, response.data["message"]
    assert response.data["reference"] == match.group(1)
    return match.group(1)


@pytest.mark.parametrize(
    "error_type,status_code,expected_code,expected_message",
    [
        (errors.ClientNotFoundError, 404, "not_found", NOT_FOUND_TEXT),
        (errors.ClientRateLimitError, 429, "throttled", RATE_LIMITED_TEXT),
        (errors.ClientMethodNotAllowedError, 405, "method_not_allowed", REFUSED_TEXT),
        (errors.ClientConflictError, 409, "conflict", REFUSED_TEXT),
        (errors.ClientHTTPStatusError, 423, "locked", REFUSED_TEXT),
    ],
)
def test_upstream_refusal_of_an_unexpected_shape_shows_a_fixed_message_and_logs_the_body(
    captured_logs, error_type, status_code, expected_code, expected_message
):
    exc = _status_error(error_type, status_code, "Venv 42 does not exist on sandbox-db:5432.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == status_code
    assert response.data == {
        "status_code": status_code,
        "code": expected_code,
        "message": expected_message,
    }
    assert any("Venv 42 does not exist on sandbox-db:5432." in record for record in captured_logs)


@pytest.mark.parametrize(
    "error_type,status_code",
    [
        # A 401 or 403 refuses the gateway's credentials. Passed through, a 401 would
        # sign the user out and a 403 would deny them a permission they have.
        (errors.ClientUnauthorizedError, 401),
        (errors.ClientForbiddenError, 403),
        (errors.ClientServerError, 500),
        (errors.ClientNotImplementedError, 501),
        (errors.ClientBadGatewayError, 502),
        (errors.ClientUnavailableError, 503),
        (errors.ClientGatewayTimeoutError, 504),
    ],
)
def test_upstream_failure_is_a_bad_gateway_citing_the_reference_its_body_is_logged_under(
    captured_logs, error_type, status_code
):
    exc = _status_error(error_type, status_code, "Venv 42 does not exist on sandbox-db:5432.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == 502
    assert response.data["code"] == "upstream_service_error"
    reference = _cited_reference(response)
    assert any(
        reference in record and "Venv 42 does not exist on sandbox-db:5432." in record
        for record in captured_logs
    )


def _server_error_body(reference: object) -> str:
    """A 500 body as foundation's server error handler writes it."""
    return json.dumps(
        {
            "type": "server_error",
            "errors": [{"code": "internal_error", "detail": "Something went wrong."}],
            "reference": reference,
        }
    )


def test_upstream_failure_cites_the_reference_the_upstream_logged_it_under(captured_logs):
    exc = _status_error(errors.ClientServerError, 500, _server_error_body("3f9a2c1b7d4e"))

    response = custom_exception_handler(exc, {})

    assert _cited_reference(response) == "3f9a2c1b7d4e"
    assert any("3f9a2c1b7d4e" in record for record in captured_logs)


@pytest.mark.parametrize(
    "upstream_reference",
    ["<script>", "3F9A2C1B7D4E", "3f9a2c1b7d4e0", 42, None],
    ids=["markup", "upper-case", "too-long", "not-a-string", "missing"],
)
def test_upstream_reference_that_is_not_well_formed_is_never_shown(upstream_reference):
    exc = _status_error(errors.ClientServerError, 500, _server_error_body(upstream_reference))

    response = custom_exception_handler(exc, {})

    assert _cited_reference(response) != upstream_reference


def test_unreachable_dependency_renders_as_503_citing_a_reference(captured_logs):
    exc = errors.ClientConnectionError("Could not connect to http://sandbox-manager:8000.")

    response = custom_exception_handler(exc, {})

    assert response.status_code == 503
    assert response.data["code"] == "upstream_service_unreachable"
    reference = _cited_reference(response)
    assert any(
        reference in record and "http://sandbox-manager:8000" in record
        for record in captured_logs
    )


@pytest.mark.parametrize(
    "exc",
    [errors.ClientTimeoutError(), errors.ClientTimeoutError("Read timed out.")],
    ids=["without-message", "with-message"],
)
def test_timeout_renders_as_502_citing_a_reference(exc):
    response = custom_exception_handler(exc, {})

    assert response.status_code == 502
    assert response.data["code"] == "upstream_service_error"
    _cited_reference(response)


@pytest.mark.parametrize(
    "error_type,status_code,expected_message",
    [
        (errors.ClientNotFoundError, 404, NOT_FOUND_TEXT),
        (errors.ClientValidationError, 400, REFUSED_TEXT),
        (errors.ClientRateLimitError, 429, RATE_LIMITED_TEXT),
    ],
)
def test_empty_upstream_body_of_a_refusal(error_type, status_code, expected_message):
    exc = _status_error(error_type, status_code, "")

    response = custom_exception_handler(exc, {})

    assert response.status_code == status_code
    assert response.data["message"] == expected_message


def test_empty_upstream_body_of_a_failure():
    exc = _status_error(errors.ClientServerError, 500, "")

    response = custom_exception_handler(exc, {})

    assert response.status_code == 502
    _cited_reference(response)
