"""DELETE /api/admin/organizations/<id>/: a superadmin deletes an org after typing a confirmation phrase."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.label_models import Label
from tables.models.graph_models import Graph
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole


@pytest.fixture(autouse=True)
def _stub_storage(mocker):
    # Object storage is an external boundary; the deletion lists and removes the org's prefix there.
    backend = mocker.MagicMock()
    backend.list_all_objects.return_value = [("a.txt", 10, "")]
    return mocker.patch("tables.services.organization_deletion.get_storage_backend", return_value=backend)


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)


@pytest.fixture
def doomed_org(db):
    org = Organization.objects.create(name="Doomed API Org")
    Graph.objects.create(name="g", org=org)
    Label.objects.create(name="doomed-label", org=org)
    return org


@pytest.fixture
def surviving_org(db):
    return Organization.objects.create(name="Surviving API Org")


@pytest.fixture
def superadmin(db, django_user_model):
    return django_user_model.objects.create_user(email="sa-org@x.com", password="StrongPass123!", is_superadmin=True)


@pytest.fixture
def org_admin(db, django_user_model, doomed_org, role_org_admin):
    user = django_user_model.objects.create_user(email="oa-org@x.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=doomed_org, role=role_org_admin)
    return user


def url(org_id):
    return f"/api/admin/organizations/{org_id}/"


def phrase_body(org):
    return {"verification_phrase": f"delete-{org.name}"}


def as_user(user, token=None):
    client = APIClient()
    client.force_authenticate(user=user, token=token)
    return client


def _intact(org):
    return Organization.objects.filter(pk=org.pk).exists() and Graph.objects.filter(org_id=org.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["anonymous", "org-admin", "superadmin-api-key"])
def test_only_a_signed_in_superadmin_can_delete_an_org(
    superadmin, org_admin, doomed_org, surviving_org, issue_api_key, caller
):
    if caller == "anonymous":
        client, expected = APIClient(), status.HTTP_401_UNAUTHORIZED
    elif caller == "org-admin":
        client, expected = as_user(org_admin), status.HTTP_403_FORBIDDEN
    else:
        client, expected = as_user(superadmin, token=issue_api_key(user=superadmin)[1]), status.HTTP_403_FORBIDDEN

    response = client.delete(url(doomed_org.pk), data=phrase_body(doomed_org), format="json")

    assert response.status_code == expected
    assert _intact(doomed_org)


@pytest.mark.django_db
@pytest.mark.parametrize("body", [None, {"verification_phrase": 1}], ids=["no-body", "malformed-body-ignored"])
def test_dry_run_reports_and_deletes_nothing(superadmin, doomed_org, surviving_org, body):
    kwargs = {} if body is None else {"data": body, "format": "json"}

    response = as_user(superadmin).delete(f"{url(doomed_org.pk)}?dry_run=true", **kwargs)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["organization_id"] == doomed_org.pk
    assert _intact(doomed_org)


@pytest.mark.django_db
def test_the_preview_matches_what_the_delete_does(superadmin, doomed_org, surviving_org):
    from tables.models.crew_models import Agent, Crew, Task
    from tables.models.knowledge_models.collection_models import SourceCollection

    # A SourceCollection and a Task are swept outside the Collector's own closure,
    # so this exercises the merged-count report.
    SourceCollection.objects.create(org=doomed_org, collection_name="api-stability-docs")
    crew = Crew.objects.create(org=doomed_org, name="api-stability-crew")
    agent = Agent.objects.create(org=doomed_org, role="r", goal="g", backstory="b")
    Task.objects.create(crew=crew, agent=agent, name="t", instructions="i", expected_output="e")
    client = as_user(superadmin)

    preview = client.delete(f"{url(doomed_org.pk)}?dry_run=true").data
    actual = client.delete(url(doomed_org.pk), data=phrase_body(doomed_org), format="json").data

    assert preview["affected_resources"] == actual["affected_resources"]


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["", "?dry_run=maybe", "?dry_run"], ids=["no-flag", "unrecognised-value", "bare-flag"])
def test_delete_removes_the_org_and_its_content_and_nothing_else(superadmin, doomed_org, surviving_org, query):
    """Only dry_run=true/1 previews; anything else is a real delete."""
    keeper = Graph.objects.create(name="keeper", org=surviving_org)

    response = as_user(superadmin).delete(url(doomed_org.pk) + query, data=phrase_body(doomed_org), format="json")

    assert response.status_code == status.HTTP_200_OK
    assert not Organization.objects.filter(pk=doomed_org.pk).exists()
    assert not Graph.all_objects.filter(org_id=doomed_org.pk).exists()
    assert not Label._base_manager.filter(org_id=doomed_org.pk).exists()
    assert Graph.objects.filter(pk=keeper.pk, org=surviving_org).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["", "?dry_run=true"], ids=["delete", "dry-run"])
def test_the_default_org_cannot_be_deleted(superadmin, surviving_org, query):
    org = Organization.objects.create(name="Default API Org", is_default=True)

    response = as_user(superadmin).delete(url(org.pk) + query, data=phrase_body(org), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "default_organization_not_deletable"
    assert Organization.objects.filter(pk=org.pk).exists()


@pytest.mark.django_db
def test_unknown_org_is_404(superadmin):
    response = as_user(superadmin).delete(
        url(999999), data={"verification_phrase": "delete-Doomed API Org"}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["code"] == "organization_not_found"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"verification_phrase": ""},
        {"verification_phrase": "Delete-Doomed API Org"},
        {"verification_phrase": "delete Doomed API Org"},
        {"verification_phrase": "Doomed API Org"},
        {"verification_phrase": "delete-Surviving API Org"},
        {"verification_phrase": "delete-doomed api org"},
        {"verification_phrase": "delete-Doomed API Org "},
        {"verification_phrase": " delete-Doomed API Org"},
        {"verification_phrase": "delete-secret-guess"},
    ],
)
def test_real_delete_with_a_wrong_phrase_is_rejected_and_deletes_nothing(superadmin, doomed_org, surviving_org, body):
    kwargs = {} if body is None else {"data": body, "format": "json"}

    response = as_user(superadmin).delete(url(doomed_org.pk), **kwargs)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid_verification_phrase"
    assert _intact(doomed_org)
    if body and body.get("verification_phrase"):
        assert body["verification_phrase"].strip() not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body", [[], ["delete-Doomed API Org"], {"verification_phrase": 1}, {"verification_phrase": ["x"]}]
)
def test_malformed_body_is_a_form_validation_error(superadmin, doomed_org, surviving_org, body):
    response = as_user(superadmin).delete(url(doomed_org.pk), data=body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid"
    assert response.data["errors"][0]["field"] == "verification_phrase"
    assert _intact(doomed_org)


@pytest.mark.django_db
def test_rename_between_preview_and_delete_invalidates_the_phrase(superadmin, doomed_org, surviving_org):
    client = as_user(superadmin)
    stale_body = phrase_body(doomed_org)
    client.delete(f"{url(doomed_org.pk)}?dry_run=true")
    Organization.objects.filter(pk=doomed_org.pk).update(name="Renamed API Org")

    response = client.delete(url(doomed_org.pk), data=stale_body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid_verification_phrase"
    assert Organization.objects.filter(pk=doomed_org.pk).exists()
