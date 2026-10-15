"""POST /api/auth/reset-user/: a superadmin replaces every user with a new superadmin."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from rbac.models import Organization, OrganizationUser


def _reset_user(client, body):
    return client.post(reverse("reset_user"), data=body, format="json")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "expected_display_name"),
    [
        ({"email": "jane.doe@example.com"}, "Jane Doe"),
        ({"email": "jane.doe@example.com", "display_name": None}, "Jane Doe"),
        ({"email": "new-root@example.com", "display_name": "  Jane Doe  "}, "Jane Doe"),
        ({"email": "new-root@example.com", "display_name": "x" * 255}, "x" * 255),
    ],
    ids=["derived-from-email", "null-derived", "trimmed", "max-length"],
)
def test_reset_user_replaces_every_user_with_a_superadmin_of_the_default_org(
    superadmin_client, body, expected_display_name
):
    r = _reset_user(superadmin_client, {"password": "AnotherPass456!", **body})

    assert r.status_code == 201, r.content
    assert "access" in r.json()
    assert "api_key" not in r.json()
    (user,) = get_user_model().objects.all()
    assert (user.email, user.display_name) == (body["email"], expected_display_name)
    membership = OrganizationUser.objects.get(
        user=user, org__name__iexact=settings.DEFAULT_ORGANIZATION_NAME
    )
    assert (membership.role.name, membership.role.is_built_in) == ("Superadmin", True)


@pytest.mark.django_db
def test_reset_user_recreates_a_missing_default_org(superadmin_client):
    Organization.objects.filter(name__iexact=settings.DEFAULT_ORGANIZATION_NAME).delete()

    r = _reset_user(superadmin_client, {"email": "new-admin@example.com", "password": "StrongPass123!"})

    assert r.status_code == 201, r.content
    assert OrganizationUser.objects.filter(
        user__email="new-admin@example.com", org__name__iexact=settings.DEFAULT_ORGANIZATION_NAME
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "expected_errors"),
    [
        (
            {"display_name": "   "},
            [{"field": "display_name", "value": "   ",
              "reason": "Must not be blank. Omit it or use null to derive it from the email."}],
        ),
        (
            {"display_name": "x" * 256},
            [{"field": "display_name", "value": "x" * 256, "reason": "Must be 255 characters or fewer."}],
        ),
        (
            {"display_name": 123},
            [{"field": "display_name", "value": 123, "reason": "Must be a string or null."}],
        ),
        ({"email": "not-an-email", "display_name": "   "}, {"email", "display_name"}),
        ({"password": "12345"}, {"password"}),
    ],
    ids=["blank-display-name", "too-long-display-name", "non-string-display-name", "email-and-display-name", "weak-password"],
)
def test_invalid_reset_user_is_rejected_and_keeps_every_user(superadmin_client, superadmin_user, body, expected_errors):
    r = _reset_user(superadmin_client, {"email": "new-root@example.com", "password": "AnotherPass456!", **body})

    assert r.status_code == 400
    errors = r.json()["errors"]
    if isinstance(expected_errors, set):
        assert expected_errors <= {error["field"] for error in errors}
    else:
        assert errors == expected_errors
    assert list(get_user_model().objects.values_list("email", flat=True)) == [superadmin_user.email]


@pytest.mark.django_db
def test_reset_user_requires_authentication(api_client):
    r = _reset_user(api_client, {"email": "new@example.com", "password": "StrongPass123!"})

    assert r.status_code == 401
