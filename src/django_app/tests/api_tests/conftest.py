"""Fixtures shared by several api_tests modules.

Fixtures that take `client_as`, `admin_acme` or `acme` need the cross-org fixtures
(`from tests.rbac_cross_org_fixtures import *`) in the test module.
"""

import pytest
from rbac.models.enums import Permission, ResourceType
from tables.models import LLMConfig
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.services.secrets import secret_service
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants


@pytest.fixture(params=[False, True], ids=["plain-http", "https"])
def refresh_cookie_secure(request, settings):
    """Run a test once per refresh cookie: `auth.refresh` (plain http) and `__Host-auth.refresh`."""
    settings.REFRESH_COOKIE_SECURE = request.param
    return request.param


@pytest.fixture
def retention_seven_days(settings):
    # A developer's local .env can set DJANGO_RECYCLE_BIN_RETENTION_DAYS.
    settings.RECYCLE_BIN_RETENTION_DAYS = 7


@pytest.fixture
def acme_admin_client(client_as, admin_acme, acme):
    """An Acme org admin with Acme as the active org."""
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def secret_a(default_org):
    return secret_service.create(
        text="sk-fkuse-a", org=default_org, name="FKUSE_SECRET_A"
    )


@pytest.fixture
def llm_config_pointing_at_secret_a(gpt_4o_llm, default_org, secret_a) -> LLMConfig:
    return LLMConfig.objects.create(
        custom_name="fkuse-llm-config",
        model=gpt_4o_llm,
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def python_code_tool_pointing_at_secret_a(default_org, secret_a) -> PythonCodeTool:
    python_code = PythonCode.objects.create(
        code="def main(**kwargs):\n    return 1\n",
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )
    python_code.secrets.set([secret_a])
    return PythonCodeTool.objects.create(
        name="fkuse-python-code-tool",
        description="fkuse python code tool",
        python_code=python_code,
        org=default_org,
    )


@pytest.fixture
def no_use_client_6b(db, django_user_model, default_org):
    """Holds READ (not USE) on secrets, plus full CRUD on the resources 6b's five viewsets gate on."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="fkuse6b_nouse@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.LLM_CONFIGS.value: FULL_CRUD,
            ResourceType.VOICE.value: FULL_CRUD,
            ResourceType.TOOLS.value: FULL_CRUD,
            ResourceType.FLOWS.value: FULL_CRUD,
        },
    )


@pytest.fixture
def use_client_6b(db, django_user_model, default_org):
    """Holds READ + USE on secrets, plus full CRUD on the resources 6b's five viewsets gate on."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="fkuse6b_use@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ | Permission.USE),
            ResourceType.LLM_CONFIGS.value: FULL_CRUD,
            ResourceType.VOICE.value: FULL_CRUD,
            ResourceType.TOOLS.value: FULL_CRUD,
            ResourceType.FLOWS.value: FULL_CRUD,
        },
    )
