"""DELETE /api/admin/users/<id>/: a superadmin deletes a user after typing a confirmation phrase."""

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
    return django_user_model.objects.create_user(email="sa-del@x.com", password="StrongPass123!", is_superadmin=True)


@pytest.fixture
def member(db, django_user_model, org, role_member):
    user = django_user_model.objects.create_user(email="member-del@x.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role_member)
    return user


@pytest.fixture
def victim(db, django_user_model):
    return django_user_model.objects.create_user(email="victim@x.com", password="StrongPass123!")


def url(user_id):
    return f"/api/admin/users/{user_id}/"


def phrase_body(user):
    return {"verification_phrase": f"delete-{user.email}"}


def as_user(user, token=None):
    client = APIClient()
    client.force_authenticate(user=user, token=token)
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["anonymous", "member", "superadmin-api-key"])
def test_only_a_signed_in_superadmin_can_delete_a_user(
    superadmin, member, victim, django_user_model, issue_api_key, caller
):
    if caller == "anonymous":
        client, expected = APIClient(), status.HTTP_401_UNAUTHORIZED
    elif caller == "member":
        client, expected = as_user(member), status.HTTP_403_FORBIDDEN
    else:
        client, expected = as_user(superadmin, token=issue_api_key(user=superadmin)[1]), status.HTTP_403_FORBIDDEN

    response = client.delete(url(victim.pk), data=phrase_body(victim), format="json")

    assert response.status_code == expected
    assert django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("body", [None, []], ids=["no-body", "malformed-body-ignored"])
def test_dry_run_reports_and_deletes_nothing(superadmin, victim, django_user_model, body):
    kwargs = {} if body is None else {"data": body, "format": "json"}

    response = as_user(superadmin).delete(f"{url(victim.pk)}?dry_run=true", **kwargs)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["user_id"] == victim.pk
    assert django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_the_preview_matches_what_the_delete_does(superadmin, victim):
    # A real outstanding refresh token exercises revoke_all_credentials_for_user too.
    from rest_framework_simplejwt.tokens import RefreshToken

    RefreshToken.for_user(victim)
    client = as_user(superadmin)

    preview = client.delete(f"{url(victim.pk)}?dry_run=true").data
    actual = client.delete(url(victim.pk), data=phrase_body(victim), format="json").data

    assert preview["affected_resources"] == actual["affected_resources"]


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["", "?dry_run=maybe", "?dry_run"], ids=["no-flag", "unrecognised-value", "bare-flag"])
def test_delete_removes_the_user_and_keeps_their_content_without_an_author(
    superadmin, victim, org, django_user_model, query
):
    """Only dry_run=true/1 previews; anything else is a real delete."""
    graph = Graph.objects.create(name="authored", org=org, created_by=victim)

    response = as_user(superadmin).delete(url(victim.pk) + query, data=phrase_body(victim), format="json")

    assert response.status_code == status.HTTP_200_OK
    assert not django_user_model.objects.filter(pk=victim.pk).exists()
    graph.refresh_from_db()
    assert graph.created_by is None


@pytest.mark.django_db
def test_cannot_delete_self(superadmin):
    response = as_user(superadmin).delete(url(superadmin.pk), data=phrase_body(superadmin), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "cannot_delete_self"


@pytest.mark.django_db
def test_unknown_user_is_404(superadmin):
    response = as_user(superadmin).delete(
        url(999999), data={"verification_phrase": "delete-victim@x.com"}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["code"] == "user_not_found"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"verification_phrase": ""},
        {"verification_phrase": "Delete-victim@x.com"},
        {"verification_phrase": "delete victim@x.com"},
        {"verification_phrase": "victim@x.com"},
        {"verification_phrase": "delete-other@x.com"},
        {"verification_phrase": "delete-VICTIM@x.com"},
        {"verification_phrase": "delete-victim@x.com "},
        {"verification_phrase": "delete-victim@x.co"},
    ],
)
def test_real_delete_with_a_wrong_phrase_is_rejected_and_deletes_nothing(superadmin, victim, django_user_model, body):
    kwargs = {} if body is None else {"data": body, "format": "json"}

    response = as_user(superadmin).delete(url(victim.pk), **kwargs)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid_verification_phrase"
    assert django_user_model.objects.filter(pk=victim.pk).exists()
    # The error must not echo the guess back (it would confirm or leak the email).
    if body and body.get("verification_phrase"):
        assert body["verification_phrase"].strip() not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        [],
        ["delete-victim@x.com"],
        {"verification_phrase": 1},
        {"verification_phrase": {"a": 1}},
        {"verification_phrase": ["victim@x.com"]},
    ],
)
def test_malformed_body_is_a_form_validation_error_that_echoes_nothing(superadmin, victim, django_user_model, body):
    response = as_user(superadmin).delete(url(victim.pk), data=body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid"
    assert response.data["errors"][0]["field"] == "verification_phrase"
    assert "victim@x.com" not in response.content.decode()
    assert django_user_model.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db
def test_email_change_between_preview_and_delete_invalidates_the_phrase(superadmin, victim, django_user_model):
    client = as_user(superadmin)
    stale_body = phrase_body(victim)
    client.delete(f"{url(victim.pk)}?dry_run=true")
    django_user_model.objects.filter(pk=victim.pk).update(email="renamed-victim@x.com")

    response = client.delete(url(victim.pk), data=stale_body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid_verification_phrase"
    assert django_user_model.objects.filter(pk=victim.pk).exists()
