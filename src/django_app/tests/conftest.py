from pathlib import Path
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tables.models.rbac_models import ApiKey, Organization, OrganizationUser, Role

# Import shared fixtures (graph, crew, session_data, etc.)
from .fixtures import *  # noqa: F401,F403


@pytest.fixture(scope="session", autouse=True)
def flush_test_db_once(django_db_setup, django_db_blocker):
    """Flush the test DB once per session to remove stale data from previous
    runs, then re-run the data-migration seed functions that `flush` wipes
    (built-in Roles). In production these are seeded once by migration 0171
    and never touched; `flush` doesn't discriminate, so we have to re-apply."""
    from importlib import import_module

    from django.apps import apps as django_apps

    with django_db_blocker.unblock():
        call_command("flush", "--noinput")
        # Migration module names start with digits and cannot be imported via
        # `from ... import`; use importlib. Delegating to the migrations' own
        # seed functions keeps the role/permission definitions in one place.
        # Replay BOTH seeds in migration order: 0171 seeds roles + initial
        # permission bitmasks, then 0183 overrides them with the authoritative
        # bitmasks (e.g. Org Admin export on agents/projects). Re-seeding only
        # 0171 would leave tests on the stale pre-0183 permissions.
        roles_module = import_module("tables.migrations.0171_seed_builtin_roles")
        roles_module.seed_builtin_roles(django_apps, None)
        perms_module = import_module(
            "tables.migrations.0183_seed_builtin_role_permissions"
        )
        perms_module.seed_role_permissions(django_apps, None)


@pytest.fixture(autouse=True)
def clear_default_models_cache():
    from tables.models.base_models import DefaultBaseModel

    DefaultBaseModel._load_cache.clear()
    yield
    DefaultBaseModel._load_cache.clear()


@pytest.fixture
def resources_path():
    return Path("./tests/resources/").resolve()


@pytest.fixture
def tmp_path():
    return Path("./tests/tmp/").resolve()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def mock_telegram_service(mocker):
    return mocker.patch(
        "tables.services.telegram_trigger_service.TelegramTriggerService.register_telegram_trigger"
    )


# -----------------------------------
# RBAC
# -----------------------------------
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
def auth_client(api_client, jwt_tokens, default_org) -> APIClient:
    # regular_user is an Org Admin member of default_org; the shared resource
    # fixtures (graph/agent/crew) are created in the same org, so sending the
    # active-org header makes org-scoped endpoints resolve and authorize.
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}",
        HTTP_X_ORGANIZATION_ID=str(default_org.id),
    )
    return api_client


@pytest.fixture
def superadmin_jwt_tokens(superadmin_user):
    refresh = RefreshToken.for_user(superadmin_user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


@pytest.fixture
def superadmin_client(api_client, superadmin_jwt_tokens) -> APIClient:
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {superadmin_jwt_tokens['access']}"
    )
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
