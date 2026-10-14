"""Responses of the venv controller.

Mostly 2XX: error mapping would need a case per handler and every one of them costs a
live HTTP test server. The one rejection covered here is the library invariant, because
it is the only validation that happens after the body has already been parsed.
"""

from litestar import status_codes

from manager.domain.enums import VenvStatus
from tests.builders import make_library, make_venv


def test_list_returns_the_paging_envelope(client, venv_repository):
    venv_repository.seed(make_venv(name="a"), make_venv(name="b"))

    response = client.get("/venvs")

    assert response.status_code == status_codes.HTTP_200_OK
    body = response.json()
    assert body["count"] == 2
    assert body["limit"] == 0
    assert body["offset"] == 0
    assert [venv["name"] for venv in body["result"]] == ["a", "b"]


def test_list_applies_ids_limit_and_offset(client, venv_repository):
    first, second, third = venv_repository.seed(
        make_venv(name="a"), make_venv(name="b"), make_venv(name="c")
    )

    response = client.get(
        "/venvs", params={"ids": [first.id, second.id, third.id], "limit": 1, "offset": 1}
    )

    assert response.status_code == status_codes.HTTP_200_OK
    body = response.json()
    assert body["count"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert [venv["name"] for venv in body["result"]] == ["b"]


def test_retrieve_returns_the_venv(client, venv_repository):
    stored = venv_repository.seed(
        make_venv(name="data", libs=[make_library(name="pandas")], status=VenvStatus.COMPLETED)
    )[0]

    response = client.get(f"/venvs/{stored.id}")

    assert response.status_code == status_codes.HTTP_200_OK
    body = response.json()
    assert body["id"] == stored.id
    assert body["name"] == "data"
    assert body["status"] == "completed"
    assert [lib["name"] for lib in body["libs"]] == ["pandas"]


def test_create_returns_201_and_stores_the_venv(client, venv_repository):
    response = client.post(
        "/venvs",
        json={"name": "data", "libs": [{"name": "pandas", "specification": ">=2.0"}]},
    )

    assert response.status_code == status_codes.HTTP_201_CREATED
    body = response.json()
    assert body["name"] == "data"
    assert body["status"] == "declared"
    assert venv_repository.rows[body["id"]].name == "data"


def test_update_returns_the_updated_venv(client, venv_repository):
    stored = venv_repository.seed(make_venv(name="old"))[0]

    response = client.patch(f"/venvs/{stored.id}", json={"name": "new"})

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json()["name"] == "new"
    assert venv_repository.rows[stored.id].name == "new"


def test_update_of_libraries_returns_the_venv_to_declared(client, venv_repository):
    stored = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED))[0]

    response = client.patch(
        f"/venvs/{stored.id}", json={"libs": [{"name": "numpy", "specification": ""}]}
    )

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json()["status"] == "declared"


def test_remove_returns_204_and_deletes_the_venv(client, venv_repository):
    stored = venv_repository.seed(make_venv())[0]

    response = client.delete(f"/venvs/{stored.id}")

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    assert stored.id not in venv_repository.rows


def test_create_carries_the_library_description_and_pinned_version(client, venv_repository):
    response = client.post(
        "/venvs",
        json={
            "name": "data",
            "libs": [
                {
                    "name": "Pandas",
                    "description": "dataframes",
                    "specification": ">=2.0",
                    "version": "2.1.0",
                }
            ],
        },
    )

    assert response.status_code == status_codes.HTTP_201_CREATED
    assert response.json()["libs"] == [
        {
            "name": "pandas",
            "description": "dataframes",
            "specification": ">=2.0",
            "version": "2.1.0",
        }
    ]


def test_create_defaults_the_optional_library_fields(client, venv_repository):
    response = client.post("/venvs", json={"name": "data", "libs": [{"name": "pandas"}]})

    assert response.status_code == status_codes.HTTP_201_CREATED
    assert response.json()["libs"] == [
        {"name": "pandas", "description": None, "specification": "", "version": None}
    ]


def test_create_rejects_a_version_outside_its_specification(client, venv_repository):
    response = client.post(
        "/venvs",
        json={
            "name": "data",
            "libs": [{"name": "pandas", "specification": ">=2.0", "version": "1.9.0"}],
        },
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert venv_repository.rows == {}


def test_update_replaces_the_whole_library_list(client, venv_repository):
    stored = venv_repository.seed(make_venv(libs=[make_library(name="pandas")]))[0]

    response = client.patch(
        f"/venvs/{stored.id}",
        json={"libs": [{"name": "numpy", "specification": ">=1.26"}]},
    )

    assert response.status_code == status_codes.HTTP_200_OK
    assert [lib["name"] for lib in response.json()["libs"]] == ["numpy"]
    assert [lib.name for lib in venv_repository.rows[stored.id].libs] == ["numpy"]


def test_update_without_libraries_leaves_them_alone(client, venv_repository):
    stored = venv_repository.seed(make_venv(libs=[make_library(name="pandas")]))[0]

    response = client.patch(f"/venvs/{stored.id}", json={"name": "new"})

    assert response.status_code == status_codes.HTTP_200_OK
    assert [lib["name"] for lib in response.json()["libs"]] == ["pandas"]
