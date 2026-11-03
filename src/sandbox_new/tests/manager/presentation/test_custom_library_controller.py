"""Responses of the custom library controller.

One case per status the resource can answer with. The statuses are the contract a
gateway in front of this service relies on, and three of them -- 400, 404, 409 -- are
produced by domain errors travelling through the registered handlers rather than by the
controller itself, so they are worth asserting over HTTP rather than in isolation.
"""

from litestar import status_codes

from manager.domain.models import CustomLibrary


def test_list_returns_the_paging_envelope(client, uow):
    uow.custom_library_repo.seed(CustomLibrary(name="a"), CustomLibrary(name="b"))

    response = client.get("/custom-libraries")

    assert response.status_code == status_codes.HTTP_200_OK
    body = response.json()
    assert body["count"] == 2
    assert [library["name"] for library in body["result"]] == ["a", "b"]


def test_list_applies_ids_limit_and_offset(client, uow):
    first, second, third = uow.custom_library_repo.seed(
        CustomLibrary(name="a"), CustomLibrary(name="b"), CustomLibrary(name="c")
    )

    response = client.get(
        "/custom-libraries",
        params={"ids": [first.id, second.id, third.id], "limit": 1, "offset": 1},
    )

    body = response.json()
    assert body["count"] == 3
    assert [library["name"] for library in body["result"]] == ["b"]


def test_create_answers_201_with_the_id_a_client_addresses_it_by(client, uow):
    response = client.post("/custom-libraries", json={"name": "My_Library"})

    assert response.status_code == status_codes.HTTP_201_CREATED
    body = response.json()
    assert body["id"] in uow.custom_library_repo.rows
    assert body["name"] == "my-library"
    assert body["created_at"] is not None


def test_create_answers_400_for_a_name_no_distribution_could_have(client):
    response = client.post("/custom-libraries", json={"name": "my lib"})

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert response.json()["errors"][0]["attr"] == "name"


def test_create_answers_409_for_a_name_already_taken(client):
    client.post("/custom-libraries", json={"name": "my-library"})

    response = client.post("/custom-libraries", json={"name": "MY.LIBRARY"})

    assert response.status_code == status_codes.HTTP_409_CONFLICT
    assert response.json()["errors"][0]["code"] == "conflict"


def test_retrieve_answers_200(client, uow):
    stored = uow.custom_library_repo.seed(CustomLibrary(name="my-library"))[0]

    response = client.get(f"/custom-libraries/{stored.id}")

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json()["id"] == stored.id


def test_retrieve_answers_404_for_a_library_that_is_not_there(client):
    response = client.get("/custom-libraries/404")

    assert response.status_code == status_codes.HTTP_404_NOT_FOUND
    assert response.json()["errors"][0]["code"] == "not_found"


def test_update_answers_200_and_stores_the_new_name(client, uow):
    stored = uow.custom_library_repo.seed(CustomLibrary(name="before"))[0]

    response = client.patch(f"/custom-libraries/{stored.id}", json={"name": "After_Rename"})

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json()["name"] == "after-rename"
    assert uow.custom_library_repo.rows[stored.id].name == "after-rename"


def test_update_without_a_name_is_accepted_and_changes_nothing(client, uow):
    """`name` is the only field, so an empty body is what a client sends to change
    nothing; refusing it would make PATCH behave unlike the venv resource beside it."""
    stored = uow.custom_library_repo.seed(CustomLibrary(name="unchanged"))[0]

    response = client.patch(f"/custom-libraries/{stored.id}", json={})

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json()["name"] == "unchanged"


def test_update_answers_409_for_a_name_another_library_has(client, uow):
    first, second = uow.custom_library_repo.seed(
        CustomLibrary(name="first"), CustomLibrary(name="second")
    )

    response = client.patch(f"/custom-libraries/{second.id}", json={"name": "FIRST"})

    assert response.status_code == status_codes.HTTP_409_CONFLICT


def test_update_answers_404_for_a_library_that_is_not_there(client):
    assert (
        client.patch("/custom-libraries/404", json={"name": "whatever"}).status_code
        == status_codes.HTTP_404_NOT_FOUND
    )


def test_remove_answers_204_and_the_library_stops_answering(client, uow):
    stored = uow.custom_library_repo.seed(CustomLibrary(name="doomed"))[0]

    response = client.delete(f"/custom-libraries/{stored.id}")

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    assert client.get(f"/custom-libraries/{stored.id}").status_code == (
        status_codes.HTTP_404_NOT_FOUND
    )


def test_remove_answers_404_for_a_library_that_is_not_there(client):
    assert (
        client.delete("/custom-libraries/404").status_code == status_codes.HTTP_404_NOT_FOUND
    )


def test_remove_answers_409_for_a_library_a_venv_uses(client, uow):
    from manager.domain.models import Library, Venv

    stored = uow.custom_library_repo.seed(CustomLibrary(name="acme-core"))[0]
    uow.venv_repo.seed(
        Venv(name="data", libs=[Library(name="acme-core", specification=">=1", is_custom=True)])
    )

    response = client.delete(f"/custom-libraries/{stored.id}")

    assert response.status_code == status_codes.HTTP_409_CONFLICT
    assert response.json()["errors"][0]["code"] == "conflict"
