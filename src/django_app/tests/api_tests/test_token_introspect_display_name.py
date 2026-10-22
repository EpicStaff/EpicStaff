"""`POST /api/auth/introspect/` names the token's user.

The chat service identifies operators through this endpoint and shows their names to each
other, so an active response always carries a non-empty `display_name` — and only a SYSTEM
API key caller ever sees it.
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from rbac.serializers.auth import LoginSerializer

INTROSPECT_URL = "/api/auth/introspect/"
PROFILE_URL = "/api/profile/"
SYSTEM_KEY_REQUIRED = {"detail": "System API key required"}


@pytest.fixture
def operator(db):
    return get_user_model().objects.create_user(
        email="jane.operator@acme.com",
        password="OperatorStrongPass123!",
        display_name="Jane O.",
    )


def _access_token_for(user) -> str:
    # Minted the way login mints it, so the token carries the `email` claim.
    return str(LoginSerializer.get_token(user).access_token)


def _introspect_with_api_key(raw_api_key: str, token: str):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_api_key)
    return client.post(INTROSPECT_URL, data={"token": token}, format="json")


@pytest.mark.django_db
def test_introspect_returns_the_stored_display_name(env_api_key, operator):
    system_raw_key, _system_key = env_api_key

    response = _introspect_with_api_key(system_raw_key, _access_token_for(operator))

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "active": True,
        "user_id": operator.pk,
        "email": "jane.operator@acme.com",
        "display_name": "Jane O.",
        "scopes": [],
        "org_ids": [],
        "is_superadmin": False,
    }


@pytest.mark.django_db
def test_introspect_derives_the_display_name_from_email_after_the_user_clears_it(
    env_api_key, operator
):
    access = _access_token_for(operator)
    operator_client = APIClient()
    operator_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    cleared = operator_client.patch(PROFILE_URL, {"display_name": None}, format="json")
    assert cleared.status_code == status.HTTP_200_OK
    assert cleared.json()["display_name"] is None
    system_raw_key, _system_key = env_api_key

    response = _introspect_with_api_key(system_raw_key, access)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["display_name"] == "Jane Operator"


@pytest.mark.django_db
def test_introspect_of_an_inactive_token_returns_no_display_name(env_api_key, operator):
    access = _access_token_for(operator)
    operator.is_active = False
    operator.save(update_fields=["is_active"])
    system_raw_key, _system_key = env_api_key

    response = _introspect_with_api_key(system_raw_key, access)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"active": False}


@pytest.mark.django_db
def test_introspect_rejects_a_user_api_key_without_revealing_the_display_name(
    user_api_key, operator
):
    user_raw_key, _user_key = user_api_key

    response = _introspect_with_api_key(user_raw_key, _access_token_for(operator))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == SYSTEM_KEY_REQUIRED


@pytest.mark.django_db
def test_introspect_rejects_a_jwt_caller_without_revealing_the_display_name(operator):
    access = _access_token_for(operator)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    response = client.post(INTROSPECT_URL, data={"token": access}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == SYSTEM_KEY_REQUIRED
