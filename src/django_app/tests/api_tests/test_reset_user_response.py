import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tables.services.rbac.auth_service import TokenPair


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
