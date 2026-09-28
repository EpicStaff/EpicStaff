import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.graph_models import Graph
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole


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


def phrase_body(user):
    return {"verification_phrase": f"delete-{user.email}"}


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
    response = client.delete(url(victim.pk), data=phrase_body(victim), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_api_key_caller_is_forbidden(superadmin, victim, issue_api_key):
    _, api_key = issue_api_key(user=superadmin)
    client = APIClient()
    client.force_authenticate(user=superadmin, token=api_key)
    response = client.delete(url(victim.pk), data=phrase_body(victim), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_superadmin_dry_run_returns_a_report(superadmin, victim):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(f"{url(victim.pk)}?dry_run=true")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["user_id"] == victim.pk


@pytest.mark.django_db
def test_dry_run_does_not_delete(superadmin, victim, django_user_model):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    client.delete(f"{url(victim.pk)}?dry_run=true")
    assert django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_report_is_stable_across_calls(superadmin, victim):
    """Two calls against the same target return an identical affected_resources block."""
    # Enriched with a real outstanding refresh token so this exercises the
    # `blacklist_all_for_user` path over the HTTP surface, not just the service.
    from rest_framework_simplejwt.tokens import RefreshToken

    RefreshToken.for_user(victim)

    client = APIClient()
    client.force_authenticate(user=superadmin)
    preview = client.delete(f"{url(victim.pk)}?dry_run=true").data
    actual = client.delete(url(victim.pk), data=phrase_body(victim), format="json").data
    assert preview["affected_resources"] == actual["affected_resources"]


@pytest.mark.django_db
def test_delete_without_dry_run_removes_the_user(superadmin, victim, django_user_model):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(victim.pk), data=phrase_body(victim), format="json")
    assert response.status_code == status.HTTP_200_OK
    assert not django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_authored_content_survives_with_null_author(superadmin, victim, org):
    graph = Graph.objects.create(name="authored", org=org, created_by=victim)
    client = APIClient()
    client.force_authenticate(user=superadmin)
    client.delete(url(victim.pk), data=phrase_body(victim), format="json")
    graph.refresh_from_db()
    assert graph.created_by is None


@pytest.mark.django_db
def test_cannot_delete_self(superadmin):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(superadmin.pk), data=phrase_body(superadmin), format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "cannot_delete_self"


@pytest.mark.django_db
def test_unknown_user_is_404(superadmin):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(
        url(999999), data={"verification_phrase": "delete-victim@x.com"}, format="json"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["code"] == "user_not_found"


@pytest.mark.django_db
def test_unrecognized_dry_run_value_performs_a_real_delete(superadmin, victim, django_user_model):
    """Only `true`/`1` previews; any other value, like `RoleAdminViewSet`, is treated as a real delete."""
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(
        f"{url(victim.pk)}?dry_run=maybe", data=phrase_body(victim), format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    assert not django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_bare_dry_run_flag_performs_a_real_delete(superadmin, victim, django_user_model):
    """A `?dry_run` flag with no value is falsy, same as `RoleAdminViewSet._is_truthy`."""
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(f"{url(victim.pk)}?dry_run", data=phrase_body(victim), format="json")
    assert response.status_code == status.HTTP_200_OK
    assert not django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"verification_phrase": ""},
        {"verification_phrase": "Delete-victim@x.com"},
        {"verification_phrase": "delete victim@x.com"},
        {"verification_phrase": "victim@x.com"},
        {"verification_phrase": "delete-other@x.com"},
        {"verification_phrase": "delete-VICTIM@x.com"},
        {"verification_phrase": "delete-victim@x.com "},
    ],
)
def test_real_delete_with_a_wrong_phrase_is_rejected_and_deletes_nothing(
    superadmin, victim, django_user_model, body
):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(victim.pk), data=body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid_verification_phrase"
    assert django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_real_delete_without_a_body_is_rejected(superadmin, victim, django_user_model):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(victim.pk))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid_verification_phrase"
    assert django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_wrong_phrase_error_does_not_echo_the_email(superadmin, victim):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(
        url(victim.pk), data={"verification_phrase": "delete-victim@x.co"}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "victim@x.co" not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [[], ["delete-victim@x.com"], {"verification_phrase": 1}, {"verification_phrase": {"a": 1}}],
)
def test_malformed_body_is_a_form_validation_error(superadmin, victim, django_user_model, body):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(url(victim.pk), data=body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid"
    assert response.data["errors"][0]["field"] == "verification_phrase"
    assert django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_non_string_phrase_is_redacted_in_the_error(superadmin, victim):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(
        url(victim.pk), data={"verification_phrase": ["victim@x.com"]}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "victim@x.com" not in response.content.decode()


@pytest.mark.django_db
def test_dry_run_ignores_the_body(superadmin, victim, django_user_model):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    response = client.delete(f"{url(victim.pk)}?dry_run=true", data=[], format="json")

    assert response.status_code == status.HTTP_200_OK
    assert django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_email_change_between_preview_and_delete_invalidates_the_phrase(
    superadmin, victim, django_user_model
):
    client = APIClient()
    client.force_authenticate(user=superadmin)
    stale_body = phrase_body(victim)
    client.delete(f"{url(victim.pk)}?dry_run=true")
    django_user_model.objects.filter(pk=victim.pk).update(email="renamed-victim@x.com")

    response = client.delete(url(victim.pk), data=stale_body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid_verification_phrase"
    assert django_user_model.objects.filter(pk=victim.pk).exists()
