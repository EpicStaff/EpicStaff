"""A plugin's service account may reference only the secrets it created itself.

A row that references a secret also says where its value goes (an LLM config's `base_url`,
an MCP tool's URL, a Python tool's code). If a plugin could reference any of the
organization's secrets, it could aim one at a server of its own and read the value.
"""

import pytest
from django.contrib.contenttypes.models import ContentType
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from plugins.models import PluginGrant, PluginOwnedResource
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rest_framework.exceptions import ValidationError
from rest_framework.relations import ManyRelatedField
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory
from tables.models import EmbeddingConfig, LLMConfig, Secret
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.serializers.utils.secret_reference_guard_mixin import SecretReferenceGuardMixin
from tables.services.secrets import secret_service
from tables.services.secrets.reference_guard import secret_reference_guard

from tests.plugins_tests.conftest import GATEWAY_SECRET, service_account_client

pytestmark = [pytest.mark.django_db]

ORG_SECRET_NAME = "ACME_PROVIDER_KEY"
REFUSED = "This credential can reference only secrets it created"
ACCESS = [
    {"resource_type": "secrets", "actions": ["read", "create", "use"], "reason": "Stores its own keys."},
    {"resource_type": "llm_configs", "actions": ["read", "create", "update"], "reason": "Its LLM configs."},
    {"resource_type": "tools", "actions": ["read", "create", "update"], "reason": "Its tools."},
]
# The guarded (serializer, field) pairs found today; a floor, so the walk below can never
# lose serializers silently.
MINIMUM_GUARDED_FIELDS = 18


@pytest.fixture
def plugin(weather_backend):
    return weather_backend(access=ACCESS)


@pytest.fixture
def acme_key(plugin, service_account_key, acme):
    return service_account_key(plugin, acme)


@pytest.fixture
def client(acme_key, acme):
    return service_account_client(acme_key, acme)


@pytest.fixture
def org_secret(acme):
    return secret_service.create(text="sk-acme-real-key", org=acme, name=ORG_SECRET_NAME)


@pytest.fixture
def own_secret(client):
    response = client.post("/api/secrets/", {"name": "Weather key", "value": "sk-weather"}, format="json")
    assert response.status_code == 201, response.content
    return Secret.objects.get(pk=response.json()["id"])


def _refused(response, field):
    assert response.status_code == 400, response.content
    message = response.json()["message"]
    assert field in message and REFUSED in message
    assert ORG_SECRET_NAME not in response.content.decode()


# ---- the plugin's own secrets ----


def test_a_plugin_references_a_secret_it_created(client, own_secret):
    created = client.post(
        "/api/llm-configs/", {"custom_name": "Weather summaries", "api_key_secret_id": own_secret.pk}, format="json"
    )
    assert created.status_code == 201, created.content

    updated = client.patch(f"/api/llm-configs/{created.json()['id']}/", {"base_url": "https://llm.example.com"}, format="json")

    assert updated.status_code == 200, updated.content
    assert LLMConfig.objects.get(pk=created.json()["id"]).api_key_secret == own_secret


def test_a_config_linked_to_its_own_binned_secret_can_still_be_edited(client, own_secret):
    config_id = client.post(
        "/api/llm-configs/", {"custom_name": "Binned key", "api_key_secret_id": own_secret.pk}, format="json"
    ).json()["id"]
    own_secret.delete()

    response = client.patch(f"/api/llm-configs/{config_id}/", {"temperature": 0.2}, format="json")

    assert response.status_code == 200, response.content


def test_a_secret_owned_under_no_grant_of_this_plugin_is_refused(client, acme):
    secret = secret_service.create(text="sk-orphan", org=acme, name=ORG_SECRET_NAME)
    PluginOwnedResource.objects.create(
        org=acme,
        grant=None,
        plugin_identifier="weather",
        content_type=ContentType.objects.get_for_model(Secret),
        object_id=secret.pk,
    )

    response = client.post("/api/llm-configs/", {"custom_name": "Orphan", "api_key_secret_id": secret.pk}, format="json")

    _refused(response, "api_key_secret_id")


# ---- the organization's secrets ----


def test_referencing_an_org_secret_on_create_is_refused(client, org_secret):
    response = client.post(
        "/api/llm-configs/",
        {"custom_name": "Exfiltrate", "base_url": "https://attacker.example", "api_key_secret_id": org_secret.pk},
        format="json",
    )

    _refused(response, "api_key_secret_id")
    assert not LLMConfig.objects.filter(custom_name="Exfiltrate").exists()


@pytest.fixture
def org_llm_config(acme, org_secret):
    return LLMConfig.objects.create(custom_name="Acme production", org=acme, api_key_secret=org_secret)


def test_changing_only_the_base_url_of_an_org_config_with_an_org_secret_is_refused(client, org_llm_config):
    response = client.patch(f"/api/llm-configs/{org_llm_config.pk}/", {"base_url": "https://attacker.example"}, format="json")

    _refused(response, "api_key_secret_id")
    org_llm_config.refresh_from_db()
    assert org_llm_config.base_url is None


def test_resending_the_org_secret_unchanged_is_refused_too(client, org_llm_config, org_secret):
    response = client.put(
        f"/api/llm-configs/{org_llm_config.pk}/",
        {"custom_name": "Acme production", "base_url": "https://attacker.example", "api_key_secret_id": org_secret.pk},
        format="json",
    )

    _refused(response, "api_key_secret_id")


def test_an_embedding_config_with_an_org_secret_cannot_be_changed(client, acme, org_secret):
    config = EmbeddingConfig.objects.create(custom_name="Acme embeddings", org=acme, api_key_secret=org_secret)

    response = client.patch(f"/api/embedding-configs/{config.pk}/", {"custom_name": "Renamed"}, format="json")

    _refused(response, "api_key_secret_id")


def test_an_mcp_tool_cannot_send_an_org_secret(client, acme, org_secret):
    created = client.post(
        "/api/mcp-tools/",
        {"name": "Exfiltrate", "transport": "https://attacker.example/mcp", "tool_name": "x", "auth_secret_id": org_secret.pk},
        format="json",
    )
    tool = McpTool.objects.create(
        name="Acme search", transport="https://mcp.acme.example", tool_name="search", auth_secret=org_secret, org=acme
    )
    redirected = client.patch(f"/api/mcp-tools/{tool.pk}/", {"transport": "https://attacker.example/mcp"}, format="json")

    _refused(created, "auth_secret_id")
    _refused(redirected, "auth_secret_id")
    tool.refresh_from_db()
    assert tool.transport == "https://mcp.acme.example"


def test_python_code_cannot_read_an_org_secret(client, acme, org_secret):
    created = client.post(
        "/api/python-code-tool/",
        {
            "name": "Exfiltrate",
            "description": "d",
            "python_code": {"code": "def main(): return 1", "entrypoint": "main", "libraries": [], "secret_ids": [org_secret.pk]},
        },
        format="json",
    )
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    python_code.secrets.add(org_secret)
    tool = PythonCodeTool.objects.create(name="Acme tool", description="d", python_code=python_code, org=acme)
    rewritten = client.patch(
        f"/api/python-code-tool/{tool.pk}/",
        {"python_code": {"code": "def main(): return 2", "entrypoint": "main", "libraries": []}},
        format="json",
    )

    _refused(created, "secret_ids")
    _refused(rewritten, "secret_ids")
    python_code.refresh_from_db()
    assert python_code.code == "def main(): return 1"


def test_dropping_the_org_secret_is_not_a_reference(client, org_llm_config):
    response = client.patch(f"/api/llm-configs/{org_llm_config.pk}/", {"api_key_secret_id": None}, format="json")

    assert response.status_code == 200, response.content


# ---- every guarded serializer ----


def _guarded_serializer_classes():
    from tables import urls  # noqa: F401  -- importing registers every serializer

    seen, stack = set(), [SecretReferenceGuardMixin]
    while stack:
        for subclass in stack.pop().__subclasses__():
            if subclass not in seen:
                seen.add(subclass)
                stack.append(subclass)
    return sorted((cls for cls in seen if not cls.__module__.startswith("tests.")), key=lambda cls: cls.__name__)


def _plugin_request(acme_key, acme):
    request = Request(
        APIRequestFactory().post(
            "/",
            HTTP_AUTHORIZATION=f"PluginKey {acme_key}",
            HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET,
            HTTP_X_ORGANIZATION_ID=str(acme.pk),
        ),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    assert request.user.is_plugin_credential
    return request


def test_every_guarded_field_refuses_an_org_secret_and_takes_the_plugin_s_own(acme_key, acme, org_secret, own_secret):
    request = _plugin_request(acme_key, acme)
    checked, failures = [], []
    for serializer_class in _guarded_serializer_classes():
        serializer = serializer_class(context={"request": request})
        for field_name in serializer.get_secret_reference_fields():
            field = serializer.fields.get(field_name)
            if field is None or field.read_only:
                continue
            checked.append(f"{serializer_class.__name__}.{field_name}")

            def attrs(secret):
                return {field.source: [secret] if isinstance(field, ManyRelatedField) else secret}

            try:
                secret_reference_guard.assert_unchanged_or_permitted(serializer=serializer, attrs=attrs(own_secret), fields=(field_name,))
            except ValidationError as error:
                failures.append(f"{checked[-1]} refused the plugin's own secret: {error.detail}")
            with pytest.raises(ValidationError) as refused:
                secret_reference_guard.assert_unchanged_or_permitted(serializer=serializer, attrs=attrs(org_secret), fields=(field_name,))
            if REFUSED not in str(refused.value.detail.get(field_name)) or ORG_SECRET_NAME in str(refused.value.detail):
                failures.append(f"{checked[-1]} answered {refused.value.detail}")

    assert failures == []
    assert len(checked) >= MINIMUM_GUARDED_FIELDS, checked


# ---- everyone else ----


def test_a_person_with_the_same_rights_still_references_org_secrets(acme, org_secret, org_llm_config, django_user_model):
    role = Role.objects.create(name="Config editor", org=acme, is_built_in=False)
    RolePermission.objects.create(role=role, resource_type=ResourceType.SECRETS.value, permissions=int(Permission.READ | Permission.CREATE | Permission.USE))
    RolePermission.objects.create(role=role, resource_type=ResourceType.LLM_CONFIGS.value, permissions=int(Permission.READ | Permission.CREATE | Permission.UPDATE))
    person = django_user_model.objects.create_user(email="config-editor@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=person, org=acme, role=role)
    client = APIClient()
    client.force_authenticate(user=person)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    created = client.post("/api/llm-configs/", {"custom_name": "Person's", "api_key_secret_id": org_secret.pk}, format="json")
    updated = client.patch(f"/api/llm-configs/{org_llm_config.pk}/", {"base_url": "https://llm.acme.example"}, format="json")

    assert (created.status_code, updated.status_code) == (201, 200), (created.content, updated.content)


def test_a_plugin_in_another_organization_gets_not_found(plugin, service_account_key, acme, beta, org_llm_config):
    beta_client = service_account_client(service_account_key(plugin, beta), beta)

    response = beta_client.patch(f"/api/llm-configs/{org_llm_config.pk}/", {"base_url": "https://attacker.example"}, format="json")

    assert response.status_code == 404
    assert PluginGrant.objects.filter(org=beta).exists()
