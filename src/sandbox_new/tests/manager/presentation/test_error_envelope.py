"""The one shape every error answer takes.

Covered here rather than per endpoint: the point of the envelope is that a client parses
the same body whoever raised, so the cases are grouped by who raised rather than by route.
"""

import re

from foundation.utils.error_reference import REFERENCE_PATTERN
from foundation.utils.litestar import error_handler
from litestar import get, status_codes
from litestar.exceptions import ValidationException
from litestar.testing import create_test_client

from tests.builders import make_venv
from tests.public_errors import logged_with


def test_an_unknown_venv_is_a_client_error(client):
    response = client.get("/venvs/404")

    assert response.status_code == status_codes.HTTP_404_NOT_FOUND
    body = response.json()
    assert body["type"] == "client_error"
    assert [error["code"] for error in body["errors"]] == ["venv_not_found"]
    assert body["errors"][0]["attr"] is None
    assert "404" in body["errors"][0]["detail"]


def test_a_bad_field_in_the_body_names_that_field(client):
    response = client.post(
        "/venvs", json={"name": "data", "libs": [{"name": "pandas", "specification": "=>2"}]}
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    body = response.json()
    assert body["type"] == "client_error"
    assert [(error["code"], error["attr"]) for error in body["errors"]] == [
        ("value_error", "specification")
    ]


def test_an_invariant_spanning_fields_belongs_to_no_single_field(client):
    response = client.post(
        "/venvs",
        json={
            "name": "data",
            "libs": [{"name": "pandas", "specification": ">=2.0", "version": "1.9.0"}],
        },
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    error = response.json()["errors"][0]
    assert error["attr"] is None
    assert "1.9.0" in error["detail"]


def test_a_body_wrong_in_two_places_reports_both(client):
    response = client.post(
        "/venvs",
        json={"name": "data", "libs": [{"name": "", "version": "v1.2"}]},
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert [error["attr"] for error in response.json()["errors"]] == ["name", "version"]


def test_a_body_litestar_cannot_parse_names_the_field_too(client):
    """A body rejected before it reaches the handler reports fields like any other.

    Litestar raises its own exception here, with its own 400 attached, so this is the
    case that proves the catch-all does not relabel a caller's mistake as ours.
    """
    response = client.post("/venvs", json={"libs": []})

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    body = response.json()
    assert body["type"] == "client_error"
    assert [(error["code"], error["attr"]) for error in body["errors"]] == [
        ("validation_error", "name")
    ]


def test_a_body_wrong_in_two_fields_before_parsing_reports_both(client):
    response = client.post("/venvs", json={"name": 1, "libs": "nope"})

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert [error["attr"] for error in response.json()["errors"]] == ["name", "libs"]


def test_a_request_refused_without_field_details_is_still_a_validation_error():
    @get("/refuse")
    async def refuse() -> None:
        raise ValidationException(detail="The request can't be read.")

    with create_test_client(
        route_handlers=[refuse], exception_handlers=error_handler.get_handlers()
    ) as test_client:
        response = test_client.get("/refuse")

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert response.json()["errors"] == [
        {"code": "validation_error", "detail": "The request can't be read.", "attr": None}
    ]


def test_an_unknown_route_is_a_client_error(client):
    response = client.get("/venvs/1/nothing-here")

    assert response.status_code == status_codes.HTTP_404_NOT_FOUND
    assert response.json()["type"] == "client_error"


def test_a_failure_inside_the_service_cites_a_reference_instead_of_its_text(
    client, venv_repository, error_logs
):
    async def explode(*args, **kwargs):
        raise RuntimeError("the database at db.internal:5432 went away")

    venv_repository.retrieve = explode
    venv_repository.seed(make_venv())

    response = client.get("/venvs/1?token=hunter2")

    assert response.status_code == status_codes.HTTP_500_INTERNAL_SERVER_ERROR
    body = response.json()
    assert body["type"] == "server_error"
    assert re.fullmatch(REFERENCE_PATTERN, body["reference"])
    (error,) = body["errors"]
    assert error["code"] == "internal_error"
    assert error["detail"] == (
        "Something went wrong on the server. Try again or contact your administrator "
        f"(reference: {body['reference']})."
    )
    logged = logged_with(body["reference"], error_logs)
    assert "the database at db.internal:5432 went away" in logged
    # Only the message line: this test sink keeps loguru's `diagnose`, which prints the
    # request scope among the frame variables; the service's own sinks turn it off.
    message_line = logged.splitlines()[0]
    assert message_line.endswith(
        f"(reference: {body['reference']}) Unhandled error on GET /venvs/1"
    )
    assert "hunter2" not in message_line


def test_every_error_answer_has_the_same_keys_and_no_reference_for_a_caller_error(client):
    for response in (
        client.get("/venvs/404"),
        client.post("/venvs", json={"libs": []}),
        client.get("/venvs/1/nothing-here"),
    ):
        body = response.json()
        assert set(body) == {"type", "errors", "reference"}
        assert body["reference"] is None
