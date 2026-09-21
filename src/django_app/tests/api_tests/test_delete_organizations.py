import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.label_models import Label
from tables.models.graph_models import Graph
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture(autouse=True)
def _stub_storage(mocker):
    backend = mocker.MagicMock()
    backend.list_all_objects.return_value = [("a.txt", 10, "")]
    return mocker.patch(
        "tables.services.rbac.delete.organization_strategy.get_storage_backend",
        return_value=backend,
    )


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


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
    user = django_user_model.objects.create_user(
        email="sa-org@x.com", password="StrongPass123!"
    )
    user.is_superadmin = True
    user.save(update_fields=["is_superadmin"])
    return user


@pytest.fixture
def org_admin(db, django_user_model, doomed_org, role_org_admin):
    user = django_user_model.objects.create_user(
        email="oa-org@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=doomed_org, role=role_org_admin)
    return user


def url(org_id):
    return f"/api/admin/organizations/{org_id}/"


@pytest.mark.django_db
def test_anonymous_is_rejected(db, doomed_org):
    response = APIClient().delete(url(doomed_org.pk))
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


@pytest.mark.django_db
def test_org_admin_is_forbidden(org_admin, doomed_org, surviving_org):
    client = APIClient()
    client.force_authenticate(user=org_admin)
    response = client.delete(url(doomed_org.pk))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_api_key_caller_is_forbidden(
    superadmin, doomed_org, surviving_org, issue_api_key
):
    _, api_key = issue_api_key(user=superadmin)
    client = APIClient()
    client.force_authenticate(user=superadmin, token=api_key)
    response = client.delete(url(doomed_org.pk))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_dry_run_returns_a_report_and_deletes_nothing(
    superadmin, doomed_org, surviving_org
):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(f"{url(doomed_org.pk)}?dry_run=true")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["dry_run"] is True
    assert response.data["target"]["name"] == "Doomed API Org"
    assert Organization.objects.filter(pk=doomed_org.pk).exists()
    assert Graph.objects.filter(org_id=doomed_org.pk).exists()


@pytest.mark.django_db
def test_report_is_stable_across_calls(superadmin, doomed_org, surviving_org):
    """Two calls against the same target return identical database and field_updates blocks."""
    client = APIClient()
    client.force_authenticate(user=superadmin)
    preview = client.delete(f"{url(doomed_org.pk)}?dry_run=true").data
    actual = client.delete(url(doomed_org.pk)).data
    assert preview["database"] == actual["database"]
    assert preview["field_updates"] == actual["field_updates"]


@pytest.mark.django_db
def test_real_delete_removes_the_org_and_its_content(
    superadmin, doomed_org, surviving_org
):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(doomed_org.pk))

    assert response.status_code == status.HTTP_200_OK
    assert not Organization.objects.filter(pk=doomed_org.pk).exists()
    assert not Graph.objects.filter(org_id=doomed_org.pk).exists()
    assert not Label.objects.filter(org_id=doomed_org.pk).exists()


@pytest.mark.django_db
def test_neighbour_org_is_untouched(superadmin, doomed_org, surviving_org):
    keeper = Graph.objects.create(name="keeper", org=surviving_org)
    client = APIClient()
    client.force_authenticate(user=superadmin)
    client.delete(url(doomed_org.pk))

    assert Organization.objects.filter(pk=surviving_org.pk).exists()
    assert Graph.objects.filter(pk=keeper.pk).exists()


@pytest.mark.django_db
def test_default_org_is_blocked(superadmin, surviving_org, db):
    org = Organization.objects.create(name="Default API Org", is_default=True)
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(org.pk))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "default_organization_not_deletable"


@pytest.mark.django_db
def test_blocker_applies_to_dry_run_too(superadmin, surviving_org, db):
    org = Organization.objects.create(name="Default API Org 2", is_default=True)
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(f"{url(org.pk)}?dry_run=true")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "default_organization_not_deletable"


@pytest.mark.django_db
def test_unknown_org_is_404(superadmin):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(999999))
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["code"] == "organization_not_found"
