"""The one shape every error answer takes.

Covered here rather than per endpoint: the point of the envelope is that a client parses
the same body whoever raised, so the cases are grouped by who raised rather than by route.
"""

from litestar import status_codes

from tests.builders import make_venv


def test_an_unknown_venv_is_a_client_error(client):
    response = client.get("/venvs/404")

    assert response.status_code == status_codes.HTTP_404_NOT_FOUND
    body = response.json()
    assert body["type"] == "client_error"
    assert [error["code"] for error in body["errors"]] == ["not_found"]
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


def test_a_failure_inside_the_service_is_a_server_error(client, venv_repository):
    async def explode(*args, **kwargs):
        raise RuntimeError("the database went away")

    venv_repository.retrieve = explode
    venv_repository.seed(make_venv())

    response = client.get("/venvs/1")

    assert response.status_code == status_codes.HTTP_500_INTERNAL_SERVER_ERROR
    body = response.json()
    assert body["type"] == "server_error"
    assert [error["code"] for error in body["errors"]] == ["unknown"]


def test_every_error_answer_has_the_same_two_keys(client):
    for response in (
        client.get("/venvs/404"),
        client.post("/venvs", json={"libs": []}),
        client.get("/venvs/1/nothing-here"),
    ):
        assert set(response.json()) == {"type", "errors"}
