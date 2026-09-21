import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.graph_models import Graph
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Delete Users Org")


@pytest.fixture
def superadmin(db, django_user_model):
    user = django_user_model.objects.create_user(
        email="sa-del@x.com", password="StrongPass123!"
    )
    user.is_superadmin = True
    user.save(update_fields=["is_superadmin"])
    return user


@pytest.fixture
def second_superadmin(db, django_user_model):
    user = django_user_model.objects.create_user(
        email="sa2-del@x.com", password="StrongPass123!"
    )
    user.is_superadmin = True
    user.save(update_fields=["is_superadmin"])
    return user


@pytest.fixture
def member(db, django_user_model, org, role_member):
    user = django_user_model.objects.create_user(
        email="member-del@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role_member)
    return user


@pytest.fixture
def victim(db, django_user_model):
    return django_user_model.objects.create_user(
        email="victim@x.com", password="StrongPass123!"
    )


def url(user_id):
    return f"/api/admin/users/{user_id}/"


@pytest.mark.django_db
def test_anonymous_is_rejected(db, victim):
    response = APIClient().delete(url(victim.pk))
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


@pytest.mark.django_db
def test_plain_member_is_forbidden(member, victim):
    client = APIClient()
    client.force_authenticate(user=member)
    response = client.delete(url(victim.pk))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_api_key_caller_is_forbidden(superadmin, victim, issue_api_key):
    _, api_key = issue_api_key(user=superadmin)
    client = APIClient()
    client.force_authenticate(user=superadmin, token=api_key)
    response = client.delete(url(victim.pk))
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_superadmin_dry_run_returns_a_report(superadmin, victim):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(f"{url(victim.pk)}?dry_run=true")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["dry_run"] is True
    assert response.data["target"]["email"] == victim.email


@pytest.mark.django_db
def test_dry_run_does_not_delete(superadmin, victim, django_user_model):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    client.delete(f"{url(victim.pk)}?dry_run=true")
    assert django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_report_is_stable_across_calls(superadmin, victim):
    """Two calls against the same target return identical database and field_updates blocks."""
    client = APIClient()
    client.force_authenticate(user=superadmin)
    preview = client.delete(f"{url(victim.pk)}?dry_run=true").data
    actual = client.delete(url(victim.pk)).data
    assert preview["database"] == actual["database"]
    assert preview["field_updates"] == actual["field_updates"]


@pytest.mark.django_db
def test_delete_without_dry_run_removes_the_user(superadmin, victim, django_user_model):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(victim.pk))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["dry_run"] is False
    assert not django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_authored_content_survives_with_null_author(superadmin, victim, org):
    graph = Graph.objects.create(name="authored", org=org, created_by=victim)
    client = APIClient()
    client.force_authenticate(user=superadmin)
    client.delete(url(victim.pk))
    graph.refresh_from_db()
    assert graph.created_by is None


@pytest.mark.django_db
def test_cannot_delete_self(superadmin):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(superadmin.pk))
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "cannot_delete_self"


@pytest.mark.django_db
def test_cannot_delete_last_superadmin(
    superadmin, second_superadmin, db, django_user_model
):
    """`superadmin` acts while `second_superadmin` is the only active superadmin left."""
    django_user_model.objects.filter(is_superadmin=True).exclude(
        pk=second_superadmin.pk
    ).update(is_superadmin=False)
    # The actor keeps the flag it needs to pass the view gate; the target is the
    # last ACTIVE superadmin, so the blocker — not the self-delete guard — fires.
    django_user_model.objects.filter(pk=superadmin.pk).update(
        is_superadmin=True, is_active=False
    )

    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(second_superadmin.pk))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "last_superadmin"


@pytest.mark.django_db
def test_unknown_user_is_404(superadmin):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(999999))
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["code"] == "user_not_found"


@pytest.mark.django_db
def test_invalid_dry_run_value_is_400(superadmin, victim):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(f"{url(victim.pk)}?dry_run=maybe")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid"
