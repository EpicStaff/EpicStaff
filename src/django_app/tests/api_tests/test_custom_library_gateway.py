"""Custom libraries and their wheels, through the gateway.

The sandbox service knows nothing about organizations, so everything that keeps one
organization out of another's libraries lives in these endpoints. That is what these
tests are about: which rows an answer may carry, and which requests may reach the
sandbox at all.

The sandbox is the external boundary and the only thing replaced here. A refusal is
asserted together with the upstream calls it did not make, because a 404 that still
asked the sandbox for the row has already leaked that the row exists.
"""

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from proxies.sandbox.models import SandboxCustomLibraryBinding
from rbac.models import Organization
from rbac.models.enums import Permission, ResourceType
from rest_framework import status

from tests.api_tests.role_grant_clients import client_with_grants

CLIENT_PATH = "proxies.sandbox.services.CustomLibraryService.client_class"

WHEEL = {
    "id": 9,
    "version": "1.0",
    "status": "completed",
    "error": None,
    "source_filename": None,
    "wheel_filename": "mylib-1.0-py3-none-any.whl",
    "created_at": "2026-11-04T10:00:00Z",
}


@pytest.fixture
def sandbox_client():
    """The upstream sandbox, replaced so no request leaves this process."""
    with patch(CLIENT_PATH) as client_class:
        yield client_class.return_value.__enter__.return_value


@pytest.fixture
def library(default_org):
    return SandboxCustomLibraryBinding.objects.create(org_id=default_org.id, resource_id="7")


@pytest.fixture
def second_library(default_org):
    return SandboxCustomLibraryBinding.objects.create(org_id=default_org.id, resource_id="8")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org CustomLibrary Other")


@pytest.fixture
def foreign_library(other_org):
    return SandboxCustomLibraryBinding.objects.create(org_id=other_org.id, resource_id="99")


@pytest.fixture
def reader_client(db, django_user_model, default_org):
    """Holds READ on custom libraries and nothing else -- the Member's grant."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="customlib_reader@example.com",
        resource_permissions={ResourceType.CUSTOM_LIBRARIES.value: int(Permission.READ)},
    )


@pytest.fixture
def outsider_client(db, django_user_model, default_org):
    """A member of the same organization holding no grant on custom libraries."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="customlib_outsider@example.com",
        resource_permissions={ResourceType.VENVS.value: int(Permission.READ)},
    )


def upstream_library(binding: SandboxCustomLibraryBinding, name: str = "mylib") -> dict:
    """One library as the sandbox would report it."""
    return {
        "id": int(binding.resource_id),
        "name": name,
        "created_at": "2026-11-04T10:00:00Z",
        "updated_at": "2026-11-04T10:00:00Z",
    }


def upstream_page(*libraries: dict) -> dict:
    return {
        "count": len(libraries),
        "limit": 0,
        "offset": 0,
        "next": None,
        "previous": None,
        "result": list(libraries),
    }


@pytest.mark.django_db
def test_the_list_carries_this_orgs_libraries_under_their_binding_ids(
    auth_client, library, second_library, foreign_library, sandbox_client
):
    """The sandbox's own ids never leave, and a row nothing here owns is dropped.

    The sandbox is asked only for the ids of this organization, but it answers what it
    is asked plus whatever it decides to; a row without a binding is left out rather
    than trusted.
    """
    sandbox_client.list.return_value = upstream_page(
        upstream_library(library),
        upstream_library(second_library, name="otherlib"),
        {"id": 404404, "name": "nobodys", "created_at": None, "updated_at": None},
    )

    response = auth_client.get("/api/custom-libraries/")

    assert response.status_code == status.HTTP_200_OK
    assert sorted(sandbox_client.list.call_args.kwargs["ids"]) == ["7", "8"]
    assert [item["id"] for item in response.data["result"]] == [library.pk, second_library.pk]
    assert [item["name"] for item in response.data["result"]] == ["mylib", "otherlib"]


@pytest.mark.django_db
def test_an_org_with_no_libraries_asks_the_sandbox_for_nothing(
    auth_client, foreign_library, sandbox_client
):
    """An empty id list must not reach the sandbox: a query string drops it, and the
    filter would arrive as no filter at all."""
    sandbox_client.list.return_value = upstream_page()

    response = auth_client.get("/api/custom-libraries/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["result"] == []
    assert sandbox_client.list.call_args.kwargs["ids"] == []


@pytest.mark.django_db
def test_creating_a_library_binds_it_to_the_active_org(auth_client, regular_user, sandbox_client):
    sandbox_client.create.return_value = {
        "id": 11,
        "name": "mylib",
        "created_at": "2026-11-04T10:00:00Z",
        "updated_at": "2026-11-04T10:00:00Z",
    }
    upload = SimpleUploadedFile(
        "mylib-1.0-py3-none-any.whl", b"PK\x03\x04zip", content_type="application/octet-stream"
    )

    response = auth_client.post("/api/custom-libraries/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_201_CREATED
    binding = SandboxCustomLibraryBinding.objects.get(resource_id="11")
    assert response.data["id"] == binding.pk
    assert response.data["owner"]["email"] == regular_user.email
    assert binding.created_by == regular_user
    # No name travels: the sandbox reads it off the wheel it was handed.
    sent = sandbox_client.create.call_args.args[0]
    assert sent.name == "mylib-1.0-py3-none-any.whl"


@pytest.mark.django_db
def test_a_caller_that_is_not_a_person_creates_a_library_without_an_owner(
    api_client, env_api_key, default_org, sandbox_client
):
    """An API key is not a user row, and `created_by` points at one.

    Handed straight to the binding it is a 500 on a well-formed request, so the
    principal is resolved to an author first -- to nobody, here.
    """
    sandbox_client.create.return_value = {
        "id": 12,
        "name": "mylib",
        "created_at": "2026-11-04T10:00:00Z",
        "updated_at": "2026-11-04T10:00:00Z",
    }
    raw_key, _key = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(default_org.id))
    upload = SimpleUploadedFile(
        "mylib-1.0-py3-none-any.whl", b"PK\x03\x04zip", content_type="application/octet-stream"
    )

    response = api_client.post("/api/custom-libraries/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["owner"] is None
    assert SandboxCustomLibraryBinding.objects.get(resource_id="12").created_by is None


@pytest.mark.django_db
def test_creating_a_library_without_a_file_is_refused_here(auth_client, sandbox_client):
    response = auth_client.post("/api/custom-libraries/", {}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert sandbox_client.create.call_count == 0


@pytest.mark.django_db
def test_deleting_a_library_takes_its_binding_with_it(auth_client, library, sandbox_client):
    response = auth_client.delete(f"/api/custom-libraries/{library.pk}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert sandbox_client.remove.call_args.args == ("7",)
    assert not SandboxCustomLibraryBinding.objects.filter(pk=library.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("get", "/"),
        ("delete", "/"),
        ("get", "/wheels/"),
        ("post", "/wheels/"),
        ("get", "/wheels/9/"),
        ("delete", "/wheels/9/"),
        ("get", "/wheels/9/file/"),
    ],
)
def test_another_orgs_library_is_a_404_the_sandbox_never_hears_about(
    auth_client, foreign_library, sandbox_client, method, suffix
):
    """Cross-org is 404, never 403, and the refusal happens before the upstream call.

    The wheel routes are in here too: a wheel has no binding of its own, so the
    library's binding is the only thing standing between the caller and another
    organization's packages.
    """
    response = getattr(auth_client, method)(f"/api/custom-libraries/{foreign_library.pk}{suffix}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert sandbox_client.method_calls == []


@pytest.mark.django_db
def test_a_wheel_is_uploaded_under_the_library_it_was_posted_to(
    auth_client, library, sandbox_client
):
    sandbox_client.upload_wheel.return_value = WHEEL
    upload = SimpleUploadedFile(
        "mylib-1.0-py3-none-any.whl", b"PK\x03\x04zip", content_type="application/octet-stream"
    )

    response = auth_client.post(
        f"/api/custom-libraries/{library.pk}/wheels/", {"file": upload}, format="multipart"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data == WHEEL
    library_id, sent = sandbox_client.upload_wheel.call_args.args
    assert library_id == "7"
    assert sent.name == "mylib-1.0-py3-none-any.whl"


@pytest.mark.django_db
def test_an_upload_without_a_file_is_refused_here(auth_client, library, sandbox_client):
    response = auth_client.post(
        f"/api/custom-libraries/{library.pk}/wheels/", {}, format="multipart"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert sandbox_client.upload_wheel.call_count == 0


@pytest.mark.django_db
def test_the_versions_of_a_library_are_listed_under_it(auth_client, library, sandbox_client):
    sandbox_client.list_wheels.return_value = [WHEEL]

    response = auth_client.get(f"/api/custom-libraries/{library.pk}/wheels/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data == [WHEEL]
    assert sandbox_client.list_wheels.call_args.args == ("7",)


@pytest.mark.django_db
def test_the_wheel_comes_back_with_the_bytes_and_the_name_the_sandbox_gave_it(
    auth_client, library, sandbox_client
):
    """The name is the sandbox's: a wheel's filename is what pip reads it by."""
    disposition = 'attachment; filename="mylib-1.0-py3-none-any.whl"'
    sandbox_client.download_wheel.return_value = (b"PK\x03\x04wheel", disposition)

    response = auth_client.get(f"/api/custom-libraries/{library.pk}/wheels/9/file/")

    assert response.status_code == status.HTTP_200_OK
    assert response.content == b"PK\x03\x04wheel"
    assert response["Content-Disposition"] == disposition
    assert response["Content-Type"] == "application/octet-stream"


@pytest.mark.django_db
def test_deleting_one_version_leaves_the_library(auth_client, library, sandbox_client):
    response = auth_client.delete(f"/api/custom-libraries/{library.pk}/wheels/9/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert sandbox_client.remove_wheel.call_args.args == ("7", "9")
    assert SandboxCustomLibraryBinding.objects.filter(pk=library.pk).exists()


@pytest.mark.django_db
def test_reading_libraries_does_not_let_anyone_publish_one(reader_client, library, sandbox_client):
    """The whole reason custom libraries are a resource of their own: a member may
    install what is published without being able to publish."""
    sandbox_client.list_wheels.return_value = [WHEEL]

    assert (
        reader_client.get(f"/api/custom-libraries/{library.pk}/wheels/").status_code
        == status.HTTP_200_OK
    )

    def wheel() -> SimpleUploadedFile:
        return SimpleUploadedFile("mylib-1.0-py3-none-any.whl", b"PK\x03\x04", content_type="x")

    refused = [
        reader_client.post("/api/custom-libraries/", {"file": wheel()}, format="multipart"),
        reader_client.delete(f"/api/custom-libraries/{library.pk}/"),
        reader_client.post(
            f"/api/custom-libraries/{library.pk}/wheels/", {"file": wheel()}, format="multipart"
        ),
        reader_client.delete(f"/api/custom-libraries/{library.pk}/wheels/9/"),
    ]

    assert [response.status_code for response in refused] == [status.HTTP_403_FORBIDDEN] * 4
    assert sandbox_client.method_calls == [("list_wheels", ("7",), {})]


@pytest.mark.django_db
@pytest.mark.parametrize("suffix", ["/", "/wheels/", "/wheels/9/", "/wheels/9/file/"])
def test_without_a_grant_nothing_is_readable(outsider_client, library, sandbox_client, suffix):
    """A grant on venvs says nothing about the libraries they install."""
    response = outsider_client.get(f"/api/custom-libraries/{library.pk}{suffix}")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert sandbox_client.method_calls == []
