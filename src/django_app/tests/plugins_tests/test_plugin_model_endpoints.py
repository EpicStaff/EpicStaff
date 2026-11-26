"""A plugin never decides where a model configuration sends requests, not even on one it created.

A config's endpoint is its `connection` fields the catalog marks as endpoints (a base URL, an
Azure deployment, a cloud region or project). People in the organization may add their own
keys to a config a plugin wrote, so a plugin never sets, changes or clears one of those. A
model's name can act as one too, when LiteLLM takes a URL in it as the request URL
(`huggingface/https://host/v1`), so a plugin never points a config at such a model, nor
names a model that way. The name, the model and the settings otherwise stay editable.
"""

import pytest
from ai_models.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider
from ai_models.repository import CatalogRepository
from django.apps import apps
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.models import Secret
from tables.services.secrets.exceptions import ModelEndpointNotSettableError
from tables.services.secrets.secret_use_checks import check_llm_config_write
from tables.services.secrets.secret_use_service import SecretActor

from tests.plugins_tests.conftest import GATEWAY_SECRET, service_account_client

pytestmark = [pytest.mark.django_db]

REFUSED = "This credential cannot set where a model configuration sends requests"
ACCESS = [{"resource_type": "llm_configs", "actions": ["read", "create", "update"], "reason": "Its models."}]
ACME_URL = "https://llm.acme.example"
ELSEWHERE = "https://elsewhere.example"
LLM_CONFIGS = "/api/llm-configs/"
ROUTING_NAME = f"huggingface/{ELSEWHERE}/v1"


@pytest.fixture
def plugin(weather_backend):
    return weather_backend(access=ACCESS)


@pytest.fixture
def acme_key(plugin, service_account_key, acme):
    return service_account_key(plugin, acme)


@pytest.fixture
def client(acme_key, acme):
    return service_account_client(acme_key, acme)


def _builtin(provider_name, name, model_class=LLMModel, provider_field="llm_provider"):
    provider = Provider.objects.get_or_create(name=provider_name)[0]
    return model_class.objects.create(name=name, predefined=True, **{provider_field: provider})


@pytest.fixture
def gpt_4o(db):
    return _builtin("openai", "gpt-4o")


@pytest.fixture
def org_config(acme, gpt_4o):
    return LLMConfig.objects.create(
        custom_name="acme-config", model=gpt_4o, connection={"base_url": ACME_URL}, org=acme
    )


def _refused(response, *fields):
    assert response.status_code == 400, response.content
    message = response.json()["message"]
    assert REFUSED in message
    assert all(f"connection.{field}" in message for field in fields)


# ---- no config's endpoint, the organization's or its own ----


@pytest.mark.parametrize("method", ["patch", "put"])
def test_repointing_an_org_config_is_refused(client, org_config, gpt_4o, method):
    body = {"connection": {"base_url": ELSEWHERE}}
    if method == "put":
        body = {**body, "custom_name": "acme-config", "model": gpt_4o.pk}

    response = getattr(client, method)(f"{LLM_CONFIGS}{org_config.pk}/", body, format="json")

    _refused(response, "base_url")
    org_config.refresh_from_db()
    assert org_config.connection == {"base_url": ACME_URL}


def test_clearing_an_org_config_s_endpoint_is_refused(client, org_config):
    response = client.patch(f"{LLM_CONFIGS}{org_config.pk}/", {"connection": {}}, format="json")

    _refused(response, "base_url")


@pytest.mark.parametrize(
    ("provider", "model_name", "connection"),
    [
        ("openai", "gpt-4o", {"base_url": ELSEWHERE}),
        ("azure", "azure/gpt-4o", {"base_url": ELSEWHERE, "deployment_id": "elsewhere"}),
        ("vertex_ai", "gemini-2.5-flash", {"vertex_project": "their-project", "vertex_location": "us-central1"}),
    ],
    ids=["base-url", "azure-deployment", "vertex-project-and-location"],
)
def test_a_plugin_cannot_create_a_config_with_an_endpoint(client, provider, model_name, connection):
    model = _builtin(provider, model_name)

    response = client.post(
        LLM_CONFIGS, {"custom_name": "weather-config", "model": model.pk, "connection": connection}, format="json"
    )

    _refused(response, *connection)
    assert not LLMConfig.objects.filter(custom_name="weather-config").exists()


def test_a_plugin_cannot_repoint_a_config_it_created(client, gpt_4o):
    created = client.post(LLM_CONFIGS, {"custom_name": "weather-config", "model": gpt_4o.pk}, format="json")
    assert created.status_code == 201, created.content

    response = client.patch(
        f"{LLM_CONFIGS}{created.json()['id']}/", {"connection": {"base_url": ELSEWHERE}}, format="json"
    )

    _refused(response, "base_url")
    assert LLMConfig.objects.get(pk=created.json()["id"]).connection == {}


def test_the_name_model_settings_and_an_unchanged_endpoint_stay_editable(client, org_config):
    other_model = _builtin("openai", "gpt-4o-mini")

    response = client.put(
        f"{LLM_CONFIGS}{org_config.pk}/",
        {
            "custom_name": "acme-config-renamed",
            "model": other_model.pk,
            "parameters": {"temperature": 0.2},
            "connection": {"base_url": ACME_URL},
        },
        format="json",
    )

    assert response.status_code == 200, response.content
    org_config.refresh_from_db()
    assert (org_config.custom_name, org_config.model_id, org_config.connection) == (
        "acme-config-renamed",
        other_model.pk,
        {"base_url": ACME_URL},
    )


def test_a_connection_field_that_is_no_endpoint_stays_editable(client, acme):
    connection = {"base_url": ACME_URL, "api_version": "2024-06-01"}
    config = LLMConfig.objects.create(
        custom_name="acme-azure", model=_builtin("azure", "azure/gpt-4o"), connection=connection, org=acme
    )

    response = client.patch(
        f"{LLM_CONFIGS}{config.pk}/", {"connection": {**connection, "api_version": "2025-01-01"}}, format="json"
    )

    assert response.status_code == 200, response.content


def test_an_embedding_config_s_endpoint_is_not_the_plugin_s_to_set(client, acme):
    model = _builtin("openai", "text-embedding-3-small", EmbeddingModel, "embedding_provider")
    config = EmbeddingConfig.objects.create(custom_name="acme-embedder", model=model, org=acme)
    elsewhere = {"connection": {"base_url": ELSEWHERE}}

    created = client.post(
        "/api/embedding-configs/", {"custom_name": "weather-embedder", "model": model.pk, **elsewhere}, format="json"
    )
    repointed = client.patch(f"/api/embedding-configs/{config.pk}/", elsewhere, format="json")

    _refused(created, "base_url")
    _refused(repointed, "base_url")


# ---- a model whose name routes to a URL ----


def _custom_model(acme, name):
    provider = Provider.objects.get_or_create(name="openai")[0]
    return LLMModel.objects.create(name=name, llm_provider=provider, is_custom=True, org=acme)


def _refused_on(response, field_name):
    assert response.status_code == 400, response.content
    assert response.json()["message"].startswith(f"{field_name}: {REFUSED}")


def test_switching_a_config_to_a_model_that_routes_to_a_url_is_refused(client, org_config, gpt_4o, acme):
    # Refused though the config carries no secret: a person may add a key to it later.
    response = client.patch(
        f"{LLM_CONFIGS}{org_config.pk}/", {"model": _custom_model(acme, ROUTING_NAME).pk}, format="json"
    )

    _refused_on(response, "model")
    org_config.refresh_from_db()
    assert org_config.model_id == gpt_4o.pk


def test_creating_a_config_naming_a_url_model_by_provider_and_name_is_refused(client):
    Provider.objects.get_or_create(name="openai")
    response = client.post(
        LLM_CONFIGS,
        {"custom_name": "weather-config", "provider": "openai", "model_name": ROUTING_NAME},
        format="json",
    )

    _refused_on(response, "model")
    assert not LLMConfig.objects.filter(custom_name="weather-config").exists()
    assert not LLMModel.objects.filter(name=ROUTING_NAME).exists()


def test_switching_to_another_vendor_s_model_stays_allowed(client, org_config):
    # Picking a vendor is picking a provider, which a plugin may do; only a URL is refused.
    other_vendor = _builtin("anthropic", "claude-sonnet-4-6")

    response = client.patch(f"{LLM_CONFIGS}{org_config.pk}/", {"model": other_vendor.pk}, format="json")

    assert response.status_code == 200, response.content


def test_a_plugin_cannot_name_a_model_after_a_url(client, acme):
    openai = Provider.objects.get_or_create(name="openai")[0]
    own_model = _custom_model(acme, "acme-gateway-model")

    created = client.post("/api/llm-models/", {"name": ROUTING_NAME, "llm_provider": openai.pk}, format="json")
    renamed = client.patch(f"/api/llm-models/{own_model.pk}/", {"name": ROUTING_NAME}, format="json")

    _refused_on(created, "name")
    _refused_on(renamed, "name")
    own_model.refresh_from_db()
    assert own_model.name == "acme-gateway-model"
    assert not LLMModel.objects.filter(name=ROUTING_NAME).exists()


def _authenticated_principal(raw_key):
    request = Request(
        APIRequestFactory().post("/", HTTP_AUTHORIZATION=f"PluginKey {raw_key}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    return request.user


def test_every_endpoint_field_the_catalog_declares_is_refused_to_a_plugin(acme_key, acme):
    # Which fields count comes from the catalog, so a provider added there is guarded too.
    actor = SecretActor(user=_authenticated_principal(acme_key), org_id=acme.pk)
    repository = CatalogRepository.default()
    unguarded = []
    for provider_name in ("openai", "azure", "bedrock", "vertex_ai", "oci", "watsonx", "sagemaker"):
        config = LLMConfig(model=LLMModel(name="any", llm_provider=Provider(name=provider_name)), connection={})
        for field in repository.provider(provider_name).connection_fields:
            if not field.endpoint:
                continue
            try:
                check_llm_config_write(actor, config, {"connection": {field.name: "elsewhere"}})
            except ModelEndpointNotSettableError as refusal:
                assert refusal.fields == (f"connection.{field.name}",)
            else:
                unguarded.append(f"{provider_name}.{field.name}")

    assert unguarded == []


@pytest.mark.parametrize(
    ("config_entity_type", "model_entity_type", "model_class", "provider_field"),
    [
        (EntityType.LLM_CONFIG, EntityType.LLM_MODEL, LLMModel, "llm_provider"),
        (EntityType.EMBEDDING_CONFIG, EntityType.EMBEDDING_MODEL, EmbeddingModel, "embedding_provider"),
    ],
    ids=["llm", "embedding"],
)
def test_an_import_by_a_plugin_cannot_create_a_config_with_an_endpoint(
    acme_key, acme, config_entity_type, model_entity_type, model_class, provider_field
):
    model = _builtin("openai", "imported-model", model_class, provider_field)
    id_mapper = IDMapper()
    id_mapper.map(model_entity_type, model.pk, model.pk, was_created=False)
    strategy = entity_registry.get_strategy(config_entity_type)
    principal = _authenticated_principal(acme_key)
    entry = {"custom_name": "imported-config", "model": model.pk, "parameters": {}, "tags": []}

    with pytest.raises(ValidationError) as refusal:
        strategy.create_entity({**entry, "connection": {"base_url": ELSEWHERE}}, id_mapper, org_id=acme.pk, user=principal)

    assert REFUSED in str(refusal.value.detail["connection.base_url"])
    created = strategy.create_entity({**entry, "connection": {}}, id_mapper, org_id=acme.pk, user=principal)
    assert (created.org_id, created.connection) == (acme.pk, {})


# ---- quickstart reuses an organization's model by name ----


def test_quickstart_reusing_a_plugin_s_model_sends_the_key_to_the_vendor(client, client_as, admin_acme, acme):
    openai = Provider.objects.get_or_create(name="openai")[0]
    for url, body in (
        ("/api/llm-models/", {"name": "gpt-6-luna", "llm_provider": openai.pk}),
        ("/api/embedding-models/", {"name": "text-embedding-3-small", "embedding_provider": openai.pk}),
    ):
        # A model row cannot hold an endpoint at all.
        assert client.post(url, {**body, "base_url": ELSEWHERE}, format="json").status_code == 400
        assert client.post(url, body, format="json").status_code == 201
    person = client_as(admin_acme)
    person.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    response = person.post("/api/quickstart/", {"provider": "openai", "api_key": "sk-org-admin"}, format="json")

    assert response.status_code == 200, response.content
    llm_config = LLMConfig.objects.get(org=acme, custom_name=response.json()["config_name"])
    embedding_config = EmbeddingConfig.objects.get(org=acme, custom_name=response.json()["config_name"])
    assert (llm_config.model.name, llm_config.connection) == ("gpt-6-luna", {})
    assert embedding_config.connection == {}


# ---- everyone else ----


def test_a_person_with_the_same_rights_still_sets_config_endpoints(acme, org_config, gpt_4o, django_user_model):
    role = Role.objects.create(name="Config editor", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.LLM_CONFIGS.value, permissions=int(Permission.READ | Permission.CREATE | Permission.UPDATE)
    )
    person = django_user_model.objects.create_user(email="config-editor@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=person, org=acme, role=role)
    client = APIClient()
    client.force_authenticate(user=person)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))
    elsewhere = {"connection": {"base_url": ELSEWHERE}}

    repointed = client.patch(f"{LLM_CONFIGS}{org_config.pk}/", elsewhere, format="json")
    created = client.post(LLM_CONFIGS, {"custom_name": "person-config", "model": gpt_4o.pk, **elsewhere}, format="json")

    assert (repointed.status_code, created.status_code) == (200, 201), (repointed.content, created.content)


def test_a_plugin_in_another_organization_gets_not_found(plugin, service_account_key, beta, org_config):
    beta_client = service_account_client(service_account_key(plugin, beta), beta)

    response = beta_client.patch(f"{LLM_CONFIGS}{org_config.pk}/", {"custom_name": "renamed"}, format="json")

    assert response.status_code == 404
    org_config.refresh_from_db()
    assert org_config.custom_name == "acme-config"


# ---- no model a secret-holding config points at holds an endpoint column ----

ENDPOINT_FIELD_NAMES = {"base_url", "deployment_id", "deployment", "api_version"}


def test_no_model_a_config_with_a_secret_points_at_holds_an_endpoint():
    # Endpoints live in each config's `connection`, guarded with the config. One back on a
    # model row would let switching models move a secret past that guard.
    targets = {}
    for config in apps.get_models():
        if not any(getattr(field, "related_model", None) is Secret for field in config._meta.concrete_fields):
            continue
        for field in config._meta.concrete_fields:
            target = getattr(field, "related_model", None)
            if field.many_to_one and target not in (None, Secret):
                targets[target._meta.label] = ENDPOINT_FIELD_NAMES & {
                    target_field.name for target_field in target._meta.concrete_fields
                }

    assert {"ai_models.LLMModel", "ai_models.EmbeddingModel"} <= targets.keys()
    assert {label: fields for label, fields in targets.items() if fields} == {}
