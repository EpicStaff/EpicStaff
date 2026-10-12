import pytest
from rest_framework.test import APIClient

from tables.models import LLMConfig, Provider
from tables.models.default_models import DefaultModels
from tables.models.embedding_models import EmbeddingConfig
from tables.models.realtime_models import GeminiRealtimeConfig, OpenAIRealtimeConfig
from rbac.models import Organization, OrganizationUser, Role, RolePermission
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from tables.services.quickstart_service import QuickstartService


def _org_admin(django_user_model, org, email):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _member(django_user_model, org, email):
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.mark.django_db
def test_quickstart_configs_land_in_active_org(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="qa@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    # quickstart looks the provider up by name (key in PROVIDER_CONFIGS);
    # the *Model rows are get_or_create'd by the service and stay global.
    Provider.objects.create(name="openai")

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))

    resp = client.post(
        "/api/quickstart/", {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    assert resp.status_code == 200, resp.data

    # every config quickstart created is stamped with the active org
    assert LLMConfig.objects.exists()
    assert LLMConfig.objects.exclude(org=org).count() == 0
    assert EmbeddingConfig.objects.exclude(org=org).count() == 0
    # The provider-specific realtime config (org is now
    # NOT NULL on this model) must also be stamped, not left null -> 500.
    assert OpenAIRealtimeConfig.objects.exists()
    assert OpenAIRealtimeConfig.objects.exclude(org=org).count() == 0


@pytest.mark.django_db
def test_quickstart_gemini_realtime_config_lands_in_active_org(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="qa-gemini@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    Provider.objects.create(name="gemini")

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))

    resp = client.post(
        "/api/quickstart/", {"provider": "gemini", "api_key": "sk-test"}, format="json"
    )
    assert resp.status_code == 200, resp.data

    assert GeminiRealtimeConfig.objects.exists()
    assert GeminiRealtimeConfig.objects.exclude(org=org).count() == 0


@pytest.mark.django_db
def test_quickstart_requires_org_header(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="qa2@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    Provider.objects.create(name="openai")

    client = APIClient()
    client.force_authenticate(user=user)  # no X-Organization-Id

    resp = client.post(
        "/api/quickstart/", {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    assert resp.status_code == 400  # org_context_required


@pytest.mark.django_db
def test_quickstart_post_denied_without_llm_config_create(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    user = _member(django_user_model, org, "qm@example.com")  # llm_configs READ only
    Provider.objects.create(name="openai")
    resp = _client(user, org).post(
        "/api/quickstart/", {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    assert resp.status_code == 403  # needs LLM_CONFIGS CREATE


@pytest.mark.django_db
def test_quickstart_apply_denied_for_member(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    member = _member(django_user_model, org, "qmember@example.com")  # llm_configs READ only
    resp = _client(member, org).post("/api/quickstart/apply/", {}, format="json")
    assert resp.status_code == 403  # needs LLM_CONFIGS CREATE and UPDATE


@pytest.mark.django_db
@pytest.mark.parametrize(
    "llm_config_permissions",
    [Permission.READ | Permission.CREATE, Permission.READ | Permission.UPDATE],
    ids=["create_without_update", "update_without_create"],
)
def test_quickstart_apply_denied_without_both_create_and_update(
    db, django_user_model, llm_config_permissions
):
    org = Organization.objects.create(name="Org A")
    Provider.objects.create(name="openai")
    QuickstartService().quickstart(provider="openai", api_key="sk-test", org_id=org.id, user=None)
    role = Role.objects.create(name="LLM half-writer", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.LLM_CONFIGS,
        permissions=int(llm_config_permissions),
    )
    user = django_user_model.objects.create_user(
        email="qhalf@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)

    resp = _client(user, org).post("/api/quickstart/apply/", {}, format="json")

    assert resp.status_code == 403
    assert not DefaultModels.objects.filter(org=org).exists()


@pytest.mark.django_db
def test_quickstart_apply_allowed_for_org_admin(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    Provider.objects.create(name="openai")
    QuickstartService().quickstart(provider="openai", api_key="sk-test", org_id=org.id, user=None)
    admin = _org_admin(django_user_model, org, "qadmin@example.com")

    resp = _client(admin, org).post("/api/quickstart/apply/", {}, format="json")

    assert resp.status_code == 200, resp.data
    llm_config = LLMConfig.objects.get(org=org)
    assert DefaultModels.objects.get(org=org).agent_llm_config_id == llm_config.id


@pytest.mark.django_db
def test_quickstart_apply_writes_only_the_active_orgs_default_models(db, django_user_model):
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")
    Provider.objects.create(name="openai")
    QuickstartService().quickstart(provider="openai", api_key="sk-a", org_id=org_a.id, user=None)
    QuickstartService().quickstart(provider="openai", api_key="sk-b", org_id=org_b.id, user=None)
    admin_b = _org_admin(django_user_model, org_b, "qadmin-b@example.com")

    resp = _client(admin_b, org_b).post("/api/quickstart/apply/", {}, format="json")

    assert resp.status_code == 200, resp.data
    assert DefaultModels.objects.get(org=org_b).agent_llm_config_id == (
        LLMConfig.objects.get(org=org_b).id
    )
    assert not DefaultModels.objects.filter(org=org_a).exists()


@pytest.mark.django_db
def test_apply_to_default_models_ignores_same_named_config_of_another_org(db):
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")
    LLMConfig.objects.create(custom_name="shared-name", org=org_a)
    EmbeddingConfig.objects.create(custom_name="shared-name", org=org_a)
    own_llm_config = LLMConfig.objects.create(custom_name="shared-name", org=org_b)
    own_embedding_config = EmbeddingConfig.objects.create(custom_name="shared-name", org=org_b)

    default_models = QuickstartService().apply_to_default_models("shared-name", org_id=org_b.id)

    assert default_models.org_id == org_b.id
    assert default_models.agent_llm_config_id == own_llm_config.id
    assert default_models.memory_embedding_config_id == own_embedding_config.id


@pytest.mark.django_db
def test_quickstart_apply_allowed_for_superadmin(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    Provider.objects.create(name="openai")
    QuickstartService().quickstart(
        provider="openai", api_key="sk-test", org_id=org.id, user=None
    )  # seed a config
    root = django_user_model.objects.create_user(
        email="root@example.com", password="StrongPass123!", is_superadmin=True
    )
    resp = _client(root, org).post("/api/quickstart/apply/", {}, format="json")
    assert resp.status_code == 200, resp.data


@pytest.mark.django_db
def test_quickstart_get_last_config_scoped_to_active_org(db, django_user_model):
    # org_a runs quickstart; org_b must not see org_a's last_config (which would
    # otherwise leak another org's config and its api key).
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")
    Provider.objects.create(name="openai")
    admin_a = _org_admin(django_user_model, org_a, "a@example.com")
    member_b = _member(django_user_model, org_b, "b@example.com")

    client_a = _client(admin_a, org_a)
    assert (
        client_a.post(
            "/api/quickstart/",
            {"provider": "openai", "api_key": "sk-a"},
            format="json",
        ).status_code
        == 200
    )

    resp_a = client_a.get("/api/quickstart/")
    assert resp_a.status_code == 200
    assert resp_a.data["last_config"] is not None

    # org_b ran no quickstart and cannot see org_a's config
    resp_b = _client(member_b, org_b).get("/api/quickstart/")
    assert resp_b.status_code == 200
    assert resp_b.data["last_config"] is None


@pytest.mark.django_db
def test_quickstart_get_requires_org_membership(db, django_user_model):
    # A member of org_a sending org_b's header is not a member of org_b -> 403.
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")
    member_a = _member(django_user_model, org_a, "m@example.com")
    assert _client(member_a, org_b).get("/api/quickstart/").status_code == 403


# ---------------------------------------------------------------------------
# GET /api/quickstart/ — llm_configs READ gate
# ---------------------------------------------------------------------------

QUICKSTART_AUTHOR_DISPLAY_NAME = "Quickstart Author"
QUICKSTART_STATUS_KEYS = {"supported_providers", "last_config", "is_synced"}


def _builtin_role_user(django_user_model, org, email, role_name):
    role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _custom_role_user(django_user_model, org, email, permissions_by_resource):
    role = Role.objects.create(name=f"Custom role {email}", org=org, is_built_in=False)
    for resource_type, permissions in permissions_by_resource.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(permissions)
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _api_key_client(raw_key, org):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


def _assert_denied_without_quickstart_data(response):
    assert response.status_code == 403, response.content
    body = response.json()
    assert body["code"] == "permission_denied"
    assert QUICKSTART_STATUS_KEYS.isdisjoint(body)
    content = response.content.decode()
    assert "quickstart_openai" not in content
    assert QUICKSTART_AUTHOR_DISPLAY_NAME not in content


@pytest.fixture
def quickstart_org(db):
    yield Organization.objects.create(name="Quickstart Org")


@pytest.fixture
def quickstart_author(db, django_user_model, quickstart_org):
    """Org admin who ran the org's last quickstart, so its configs carry an author."""
    Provider.objects.create(name="openai")
    author = _org_admin(django_user_model, quickstart_org, "qauthor@example.com")
    author.display_name = QUICKSTART_AUTHOR_DISPLAY_NAME
    author.save(update_fields=["display_name"])
    QuickstartService().quickstart(
        provider="openai", api_key="sk-test", org_id=quickstart_org.id, user=author
    )
    yield author


LLM_CONFIGS_READ_MISSING = pytest.mark.parametrize(
    "permissions_by_resource",
    [
        {ResourceType.FLOWS: Permission.READ},
        {ResourceType.LLM_CONFIGS: Permission.CREATE | Permission.UPDATE},
    ],
    ids=["no_llm_configs_grant", "llm_configs_write_without_read"],
)


@pytest.mark.django_db
@LLM_CONFIGS_READ_MISSING
def test_quickstart_get_denied_without_llm_configs_read(
    django_user_model, quickstart_org, quickstart_author, permissions_by_resource
):
    user = _custom_role_user(
        django_user_model, quickstart_org, "qnoread@example.com", permissions_by_resource
    )

    response = _client(user, quickstart_org).get("/api/quickstart/")

    _assert_denied_without_quickstart_data(response)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role_name", [BuiltInRole.ORG_ADMIN, BuiltInRole.MEMBER, BuiltInRole.VIEWER]
)
def test_quickstart_get_allowed_for_builtin_roles(
    django_user_model, quickstart_org, quickstart_author, role_name
):
    user = _builtin_role_user(django_user_model, quickstart_org, "qbuiltin@example.com", role_name)

    response = _client(user, quickstart_org).get("/api/quickstart/")

    assert response.status_code == 200, response.content
    assert set(response.data) == QUICKSTART_STATUS_KEYS
    assert "openai" in response.data["supported_providers"]
    assert response.data["is_synced"] is False
    last_config = response.data["last_config"]
    assert last_config["config_name"] == "quickstart_openai"
    for config_key in ("llm_config", "embedding_config"):
        assert last_config[config_key]["created_by"]["id"] == quickstart_author.id
        assert (
            last_config[config_key]["created_by"]["display_name"]
            == QUICKSTART_AUTHOR_DISPLAY_NAME
        )


@pytest.mark.django_db
@LLM_CONFIGS_READ_MISSING
def test_quickstart_get_denied_for_user_api_key_without_llm_configs_read(
    django_user_model, issue_api_key, quickstart_org, quickstart_author, permissions_by_resource
):
    owner = _custom_role_user(
        django_user_model, quickstart_org, "qkeynoread@example.com", permissions_by_resource
    )
    raw_key, _ = issue_api_key(user=owner)

    response = _api_key_client(raw_key, quickstart_org).get("/api/quickstart/")

    _assert_denied_without_quickstart_data(response)


@pytest.mark.django_db
def test_quickstart_get_allowed_for_user_api_key_with_llm_configs_read(
    django_user_model, issue_api_key, quickstart_org, quickstart_author
):
    owner = _custom_role_user(
        django_user_model,
        quickstart_org,
        "qkeyread@example.com",
        {ResourceType.LLM_CONFIGS: Permission.READ},
    )
    raw_key, _ = issue_api_key(user=owner)

    response = _api_key_client(raw_key, quickstart_org).get("/api/quickstart/")

    assert response.status_code == 200, response.content
    assert response.data["last_config"]["config_name"] == "quickstart_openai"


@pytest.mark.django_db
def test_quickstart_get_allowed_for_system_api_key(
    issue_api_key, quickstart_org, quickstart_author
):
    raw_key, _ = issue_api_key(user=None)

    response = _api_key_client(raw_key, quickstart_org).get("/api/quickstart/")

    assert response.status_code == 200, response.content
    assert response.data["last_config"]["config_name"] == "quickstart_openai"
