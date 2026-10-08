import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from rbac.identity.tokens import TokenPair


@pytest.fixture
def superadmin(db):
    return get_user_model().objects.create_superuser(
        email="root@example.com", password="StrongPass123!"
    )


@pytest.mark.django_db
def test_reset_user_returns_access_and_no_api_key(api_client, superadmin):
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {TokenPair.for_user(superadmin).access}"
    )

    r = api_client.post(
        reverse("reset_user"),
        data={"email": "new-root@example.com", "password": "AnotherPass456!"},
        format="json",
    )

    assert r.status_code == 201
    body = r.json()
    assert "access" in body
    assert "api_key" not in body
    assert get_user_model().objects.get().email == "new-root@example.com"


@pytest.mark.django_db
def test_reset_user_derives_display_name_from_email(api_client, superadmin):
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {TokenPair.for_user(superadmin).access}"
    )

    r = api_client.post(
        reverse("reset_user"),
        data={"email": "jane.doe@example.com", "password": "AnotherPass456!"},
        format="json",
    )

    assert r.status_code == 201
    assert get_user_model().objects.get().display_name == "Jane Doe"


def _reset_user(api_client, superadmin, body):
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {TokenPair.for_user(superadmin).access}"
    )
    return api_client.post(reverse("reset_user"), data=body, format="json")


@pytest.mark.django_db
def test_reset_user_derives_display_name_when_null(api_client, superadmin):
    r = _reset_user(
        api_client,
        superadmin,
        {
            "email": "jane.doe@example.com",
            "password": "AnotherPass456!",
            "display_name": None,
        },
    )

    assert r.status_code == 201
    assert get_user_model().objects.get().display_name == "Jane Doe"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("display_name", "saved"),
    [("  Jane Doe  ", "Jane Doe"), ("x" * 255, "x" * 255)],
    ids=["trimmed", "max-length"],
)
def test_reset_user_saves_display_name_from_body(
    api_client, superadmin, display_name, saved
):
    r = _reset_user(
        api_client,
        superadmin,
        {
            "email": "new-root@example.com",
            "password": "AnotherPass456!",
            "display_name": display_name,
        },
    )

    assert r.status_code == 201
    assert get_user_model().objects.get().display_name == saved


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("display_name", "reason"),
    [
        ("   ", "Must not be blank. Omit it or use null to derive it from the email."),
        ("x" * 256, "Must be 255 characters or fewer."),
        (123, "Must be a string or null."),
    ],
    ids=["blank", "too-long", "not-a-string"],
)
def test_reset_user_rejects_invalid_display_name_and_keeps_users(
    api_client, superadmin, display_name, reason
):
    r = _reset_user(
        api_client,
        superadmin,
        {
            "email": "new-root@example.com",
            "password": "AnotherPass456!",
            "display_name": display_name,
        },
    )

    assert r.status_code == 400
    assert r.json()["errors"] == [
        {"field": "display_name", "value": display_name, "reason": reason}
    ]
    assert list(get_user_model().objects.values_list("email", flat=True)) == [
        "root@example.com"
    ]


@pytest.mark.django_db
def test_reset_user_aggregates_display_name_error_with_email_error(
    api_client, superadmin
):
    r = _reset_user(
        api_client,
        superadmin,
        {"email": "not-an-email", "password": "AnotherPass456!", "display_name": "   "},
    )

    assert r.status_code == 400
    fields = {error["field"] for error in r.json()["errors"]}
    assert {"email", "display_name"} <= fields
