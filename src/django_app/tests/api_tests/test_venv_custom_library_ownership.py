"""A venv may only name the stored libraries its own organization has.

A stored library is named, not pointed at by id, and the sandbox knows nothing about
organizations. Without this rule a venv could name another organization's private
package, have the build install it, and read it back out by running code in the venv.

The rule lives in `VenvService`, so the importer and the data migration are held to it
as well; it is tested through the endpoints because that is the way a caller reaches
it. Both sandbox gateways are replaced: the venv one to see what a refusal did not
send, the custom library one to say what the organization has.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxCustomLibraryBinding, SandboxVenvBinding
from rbac.models import Organization
from rest_framework import status

CUSTOM_LIBRARY_CLIENT = "proxies.sandbox.services.CustomLibraryService.client_class"
VENV_CLIENT = "proxies.sandbox.services.VenvService.client_class"


@pytest.fixture
def venv_sandbox():
    with patch(VENV_CLIENT) as client_class:
        client = client_class.return_value.__enter__.return_value
        client.create.return_value = {
            "id": 4711,
            "name": "built",
            "libs": [],
            "status": "declared",
            "error": None,
        }
        client.update.return_value = {
            "id": 4711,
            "name": "built",
            "libs": [],
            "status": "declared",
            "error": None,
        }
        yield client


@pytest.fixture
def library_sandbox():
    with patch(CUSTOM_LIBRARY_CLIENT) as client_class:
        yield client_class.return_value.__enter__.return_value


@pytest.fixture
def owned_library(default_org, library_sandbox):
    """A stored library of this organization, named `my-lib` as the sandbox spells it."""
    binding = SandboxCustomLibraryBinding.objects.create(
        org_id=default_org.id, resource_id="7"
    )
    library_sandbox.list.return_value = {
        "count": 1,
        "limit": 0,
        "offset": 0,
        "next": None,
        "previous": None,
        "result": [{"id": 7, "name": "my-lib"}],
    }
    return binding


@pytest.fixture
def foreign_library(db, library_sandbox):
    """A stored library of another organization. This one has none of its own."""
    other_org = Organization.objects.create(name="Org VenvLibrary Other")
    SandboxCustomLibraryBinding.objects.create(org_id=other_org.id, resource_id="99")
    library_sandbox.list.return_value = {
        "count": 0,
        "limit": 0,
        "offset": 0,
        "next": None,
        "previous": None,
        "result": [],
    }


def venv_payload(*libs: dict) -> dict:
    return {"name": "built", "libs": list(libs)}


@pytest.mark.django_db
def test_a_venv_may_not_name_another_orgs_stored_library(
    auth_client, foreign_library, venv_sandbox
):
    response = auth_client.post(
        "/api/venvs/",
        venv_payload({"name": "their-lib", "is_custom": True}),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert venv_sandbox.method_calls == []
    assert not SandboxVenvBinding.objects.exists()


@pytest.mark.django_db
def test_the_refusal_does_not_say_whether_the_library_exists_elsewhere(
    auth_client, foreign_library, venv_sandbox
):
    """A name that exists in another organization and one that exists nowhere have to
    read the same, or the refusal is a directory of other people's package names."""
    unknown = auth_client.post(
        "/api/venvs/", venv_payload({"name": "never-created", "is_custom": True}), format="json"
    )
    elsewhere = auth_client.post(
        "/api/venvs/", venv_payload({"name": "their-lib", "is_custom": True}), format="json"
    )

    assert unknown.status_code == elsewhere.status_code == status.HTTP_400_BAD_REQUEST
    assert unknown.data["code"] == elsewhere.data["code"] == "unknown_custom_library"
    assert unknown.data["message"].replace("never-created", "X") == elsewhere.data[
        "message"
    ].replace("their-lib", "X")


@pytest.mark.django_db
@pytest.mark.parametrize("declared_name", ["my-lib", "My_Lib", "my.lib"])
def test_a_venv_may_name_its_own_stored_library_however_it_is_spelled(
    auth_client, owned_library, venv_sandbox, declared_name
):
    """Matched the way a package index matches a name, which is how the sandbox stored it."""
    payload = venv_payload({"name": declared_name, "is_custom": True})

    response = auth_client.post("/api/venvs/", payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    # Passed on as it was written: the spelling is the sandbox's to normalize.
    assert venv_sandbox.create.call_args.args[0] == payload


@pytest.mark.django_db
def test_a_package_index_library_is_not_checked_against_the_stored_ones(
    auth_client, foreign_library, venv_sandbox, library_sandbox
):
    """Without the marking an entry is a package index lookup, and `pydantic` on PyPI
    has nothing to do with a `pydantic` someone stored."""
    response = auth_client.post(
        "/api/venvs/", venv_payload({"name": "their-lib"}), format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert library_sandbox.list.call_count == 0


@pytest.mark.django_db
def test_changing_the_libraries_of_a_venv_is_checked_too(
    auth_client, default_org, foreign_library, venv_sandbox
):
    binding = SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id="4711")

    response = auth_client.patch(
        f"/api/venvs/{binding.pk}/",
        {"libs": [{"name": "their-lib", "is_custom": True}]},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert venv_sandbox.method_calls == []


@pytest.mark.django_db
def test_renaming_a_venv_asks_nothing_about_libraries(
    auth_client, default_org, venv_sandbox, library_sandbox
):
    """A change that carries no `libs` leaves them alone, so there is nothing to check."""
    binding = SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id="4711")

    response = auth_client.patch(
        f"/api/venvs/{binding.pk}/", {"name": "renamed"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert library_sandbox.list.call_count == 0
