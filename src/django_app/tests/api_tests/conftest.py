import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tables.models.rbac_models import ApiKey, Organization, OrganizationUser, Role


@pytest.fixture
def superadmin_user(db):
    return get_user_model().objects.create_superuser(
        email="superadmin@example.com",
        password="SuperStrongPass123!",
    )


@pytest.fixture
def default_org(db):
    return Organization.objects.create(name="Default Organization")


@pytest.fixture
def org_admin_role(db):
    return Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)


@pytest.fixture
def regular_user(db, default_org, org_admin_role):
    user = get_user_model().objects.create_user(
        email="user@example.com",
        password="UserStrongPass123!",
    )
    OrganizationUser.objects.create(user=user, org=default_org, role=org_admin_role)
    return user


@pytest.fixture
def jwt_tokens(regular_user):
    refresh = RefreshToken.for_user(regular_user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


@pytest.fixture
def auth_client(api_client, jwt_tokens) -> APIClient:
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")
    return api_client


@pytest.fixture
def env_api_key(db):
    raw = ApiKey.generate_raw_key()
    key = ApiKey(name="env-system")
    key.set_key(raw)
    key.save()
    return raw, key


@pytest.fixture
def user_api_key(regular_user):
    raw = ApiKey.generate_raw_key()
    key = ApiKey(name="user-key", created_by=regular_user)
    key.set_key(raw)
    key.save()
    return raw, key
