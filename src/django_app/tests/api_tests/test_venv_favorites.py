"""Marking a virtual environment as a favorite, through the gateway.

A favorite is personal: it belongs to the user who set it, not to the organization
the venv is bound to. These tests go through the endpoints because that is the only
interface the rule has.

The sandbox service is the external boundary and the only thing replaced here. It
never learns about favorites: the gateway narrows the ids it asks for, which is why
the upstream call is asserted on rather than the body it answers with.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rbac.models import Organization, OrganizationUser
from rest_framework import status
from rest_framework.test import APIClient

CLIENT_PATH = "proxies.sandbox.services.VenvService.client_class"


@pytest.fixture
def binding(default_org):
    return SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id="4711")


@pytest.fixture
def other_binding(default_org):
    return SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id="4712")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org VenvFavorite Other")


@pytest.fixture
def teammate(db, default_org, org_admin_role, django_user_model):
    """Another member of the same organization, who favorites nothing by himself."""
    user = django_user_model.objects.create_user(
        email="teammate-venv-favorite@example.com", password="TeammateStrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=default_org, role=org_admin_role)
    return user


@pytest.fixture
def teammate_client(teammate, default_org):
    client = APIClient()
    client.force_authenticate(user=teammate)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@pytest.fixture
def sandbox_client():
    """The upstream sandbox, replaced so no request leaves this process."""
    with patch(CLIENT_PATH) as client_class:
        yield client_class.return_value.__enter__.return_value


def upstream_page(*bindings: SandboxVenvBinding) -> dict:
    """The page the sandbox would answer with for these bindings."""
    result = [
        {
            "id": int(venv_binding.resource_id),
            "name": f"venv-{venv_binding.resource_id}",
            "libs": [],
            "status": "completed",
            "error": None,
        }
        for venv_binding in bindings
    ]
    return {
        "count": len(result),
        "limit": 0,
        "offset": 0,
        "next": None,
        "previous": None,
        "result": result,
    }


def favorite(client: APIClient, venv_binding: SandboxVenvBinding):
    return client.post(f"/api/venvs/{venv_binding.pk}/favorite/")


def unfavorite(client: APIClient, venv_binding: SandboxVenvBinding):
    return client.delete(f"/api/venvs/{venv_binding.pk}/favorite/")


@pytest.mark.django_db
def test_marking_and_unmarking_are_idempotent(auth_client, binding):
    """A double click must not create a second mark, nor fail to take one off."""
    assert favorite(auth_client, binding).status_code == status.HTTP_200_OK
    assert favorite(auth_client, binding).status_code == status.HTTP_200_OK
    assert binding.favorited_by.count() == 1

    assert unfavorite(auth_client, binding).status_code == status.HTTP_200_OK
    assert unfavorite(auth_client, binding).status_code == status.HTTP_200_OK
    assert binding.favorited_by.count() == 0


@pytest.mark.django_db
def test_a_favorite_belongs_to_the_user_who_set_it(
    auth_client, teammate_client, binding, sandbox_client
):
    favorite(auth_client, binding)
    sandbox_client.list.return_value = upstream_page(binding)

    mine = auth_client.get("/api/venvs/")
    theirs = teammate_client.get("/api/venvs/")

    assert [item["is_favorite"] for item in mine.data["result"]] == [True]
    assert [item["is_favorite"] for item in theirs.data["result"]] == [False]


@pytest.mark.django_db
def test_the_favorites_filter_narrows_what_the_sandbox_is_asked_for(
    auth_client, binding, other_binding, sandbox_client
):
    """The sandbox counts and pages what `ids` names, so narrowing happens here."""
    favorite(auth_client, binding)
    sandbox_client.list.return_value = upstream_page(binding)

    response = auth_client.get("/api/venvs/", {"is_favorite": "true"})

    assert response.status_code == status.HTTP_200_OK
    assert sandbox_client.list.call_args.kwargs["ids"] == [binding.resource_id]
    assert [item["id"] for item in response.data["result"]] == [binding.pk]


@pytest.mark.django_db
def test_the_favorites_filter_with_nothing_marked_asks_for_nothing(
    auth_client, binding, sandbox_client
):
    sandbox_client.list.return_value = upstream_page()

    response = auth_client.get("/api/venvs/", {"is_favorite": "true"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["result"] == []
    # An empty id list is what makes the client skip the upstream call altogether.
    assert sandbox_client.list.call_args.kwargs["ids"] == []


@pytest.mark.django_db
@pytest.mark.parametrize("query", [{}, {"is_favorite": "false"}])
def test_without_the_filter_every_venv_is_listed(
    auth_client, binding, other_binding, sandbox_client, query
):
    favorite(auth_client, binding)
    sandbox_client.list.return_value = upstream_page(binding, other_binding)

    response = auth_client.get("/api/venvs/", query)

    assert sorted(sandbox_client.list.call_args.kwargs["ids"]) == ["4711", "4712"]
    assert [item["is_favorite"] for item in response.data["result"]] == [True, False]


@pytest.mark.django_db
def test_the_filter_combines_with_the_sort_order(auth_client, binding, sandbox_client):
    """Sorting applies to what is left after the narrowing, so both travel together."""
    favorite(auth_client, binding)
    sandbox_client.list.return_value = upstream_page(binding)

    auth_client.get("/api/venvs/", {"is_favorite": "true", "order": "name_desc"})

    assert sandbox_client.list.call_args.kwargs == {
        "ids": [binding.resource_id],
        "search": None,
        "order": "name_desc",
        "limit": None,
        "offset": None,
    }


@pytest.mark.django_db
def test_a_single_venv_carries_the_mark_too(auth_client, binding, sandbox_client):
    favorite(auth_client, binding)
    sandbox_client.retrieve.return_value = upstream_page(binding)["result"][0]

    response = auth_client.get(f"/api/venvs/{binding.pk}/")

    assert response.data["is_favorite"] is True


@pytest.mark.django_db
def test_a_venv_is_nobodys_favorite_when_it_is_created(auth_client, sandbox_client):
    sandbox_client.create.return_value = {
        "id": 4713,
        "name": "fresh",
        "libs": [],
        "status": "declared",
        "error": None,
    }

    response = auth_client.post("/api/venvs/", {"name": "fresh", "libs": []}, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["is_favorite"] is False


@pytest.mark.django_db
def test_a_venv_of_another_org_cannot_be_favorited(auth_client, other_org, regular_user):
    """Cross-org is a 404, never a 403, and leaves no mark behind."""
    foreign = SandboxVenvBinding.objects.create(org_id=other_org.id, resource_id="4714")

    assert favorite(auth_client, foreign).status_code == status.HTTP_404_NOT_FOUND
    assert not regular_user.favorited_venvs.exists()


@pytest.mark.django_db
def test_deleting_a_venv_takes_its_favorites_with_it(
    auth_client, binding, regular_user, sandbox_client
):
    favorite(auth_client, binding)

    assert auth_client.delete(f"/api/venvs/{binding.pk}/").status_code == status.HTTP_204_NO_CONTENT
    assert not regular_user.favorited_venvs.exists()
