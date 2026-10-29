"""Responses of the venv controller.

Mostly 2XX: error mapping would need a case per handler and every one of them costs a
live HTTP test server. The one rejection covered here is the library invariant, because
it is the only validation that happens after the body has already been parsed.
"""

from datetime import UTC, datetime

import pytest
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


def test_list_keeps_the_venvs_whose_name_contains_the_search(client, venv_repository):
    venv_repository.seed(make_venv(name="Data Science"), make_venv(name="web"))

    response = client.get("/venvs", params={"search": "data"})

    assert response.status_code == status_codes.HTTP_200_OK
    body = response.json()
    assert body["count"] == 1
    assert [venv["name"] for venv in body["result"]] == ["Data Science"]


def test_list_counts_what_the_search_matched_rather_than_every_venv(client, venv_repository):
    venv_repository.seed(make_venv(name="a one"), make_venv(name="a two"), make_venv(name="b"))

    response = client.get("/venvs", params={"search": "a ", "limit": 1})

    body = response.json()
    assert body["count"] == 2
    assert len(body["result"]) == 1


def test_list_treats_a_blank_search_as_no_search(client, venv_repository):
    venv_repository.seed(make_venv(name="a"), make_venv(name="b"))

    response = client.get("/venvs", params={"search": "   "})

    assert response.json()["count"] == 2


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        ("default", ["b", "a"]),
        ("name_asc", ["a", "b"]),
        ("name_desc", ["b", "a"]),
    ],
)
def test_list_sorts_the_page(client, venv_repository, order, expected):
    venv_repository.seed(make_venv(id=1, name="b"), make_venv(id=2, name="a"))

    response = client.get("/venvs", params={"order": order})

    assert [venv["name"] for venv in response.json()["result"]] == expected


def test_list_rejects_an_order_it_does_not_know(client, venv_repository):
    response = client.get("/venvs", params={"order": "size"})

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST


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


def test_retrieve_carries_the_database_timestamps(client, venv_repository):
    moment = datetime(2026, 10, 14, 11, 17, 37, tzinfo=UTC)
    stored = venv_repository.seed(make_venv(created_at=moment, updated_at=moment))[0]

    response = client.get(f"/venvs/{stored.id}")

    body = response.json()
    assert datetime.fromisoformat(body["created_at"]) == moment
    assert datetime.fromisoformat(body["updated_at"]) == moment


def test_a_venv_created_through_the_api_comes_back_stamped(client):
    response = client.post("/venvs", json={"name": "data", "libs": []})

    body = response.json()
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(body["updated_at"]).tzinfo is not None


def test_update_returns_the_bumped_updated_at_and_keeps_created_at(client, venv_repository):
    stamped = datetime(2026, 10, 14, 11, 17, 37, tzinfo=UTC)
    stored = venv_repository.seed(make_venv(name="old", created_at=stamped, updated_at=stamped))[0]

    body = client.patch(f"/venvs/{stored.id}", json={"name": "new"}).json()

    assert datetime.fromisoformat(body["created_at"]) == stamped
    assert datetime.fromisoformat(body["updated_at"]) > stamped


def test_create_rejects_the_same_library_declared_twice(client, venv_repository):
    response = client.post(
        "/venvs",
        json={
            "name": "data",
            "libs": [
                {"name": "pydantic", "specification": "==2.0"},
                {"name": "pydantic", "specification": "==2.1"},
            ],
        },
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert "pydantic" in response.json()["errors"][0]["detail"]
    assert venv_repository.rows == {}
