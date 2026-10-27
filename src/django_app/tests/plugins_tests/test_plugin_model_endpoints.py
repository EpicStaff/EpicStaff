"""A plugin never decides where a model sends requests, not even on a model it created.

The organization's configs send their keys to the endpoint of the model they use, and a
person's config may come to use a plugin's model: quickstart reuses an organization's model
by name, and a person can pick one. So a plugin never sets a model's URL or deployment. The
name and the provider only choose between vendor hosts and stay editable.
"""

import pytest
from django.apps import apps
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.serializers import ModelSerializer
from rest_framework.test import APIClient, APIRequestFactory
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.models import EmbeddingConfig, LLMConfig, Provider, Secret
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel
from tables.services.secrets.pinned_principal_rules import (
    EMBEDDING_MODEL_ENDPOINT_FIELDS,
    LLM_MODEL_ENDPOINT_FIELDS,
)
from tables.views.secret_use import ModelEndpointsGuardedViewSetMixin

from tests.plugins_tests.conftest import GATEWAY_SECRET, service_account_client

pytestmark = [pytest.mark.django_db]

REFUSED = "This credential cannot set where a model sends requests"
ACCESS = [{"resource_type": "llm_configs", "actions": ["read", "create", "update"], "reason": "Its models."}]
ACME_URL = "https://llm.acme.example"
ELSEWHERE = "https://elsewhere.example"


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
def providers(db):
    return [Provider.objects.get_or_create(name=name)[0] for name in ("openai", "azure")]


@pytest.fixture
def org_llm_model(acme, providers):
    return LLMModel.objects.create(name="acme-gpt", llm_provider=providers[0], base_url=ACME_URL, org=acme, is_custom=True)


def _refused(response, *fields):
    assert response.status_code == 400, response.content
    message = response.json()["message"]
    assert REFUSED in message
    assert all(field in message for field in fields)


# ---- no model's endpoint, the organization's or its own ----


@pytest.mark.parametrize("method", ["patch", "put"])
def test_repointing_an_org_model_is_refused(client, org_llm_model, providers, method):
    body = {"base_url": ELSEWHERE} if method == "patch" else {"name": "acme-gpt", "llm_provider": providers[0].pk, "base_url": ELSEWHERE}

    response = getattr(client, method)(f"/api/llm-models/{org_llm_model.pk}/", body, format="json")

    _refused(response, "base_url")
    org_llm_model.refresh_from_db()
    assert org_llm_model.base_url == ACME_URL


def test_clearing_an_org_model_s_endpoint_is_refused(client, org_llm_model):
    response = client.patch(f"/api/llm-models/{org_llm_model.pk}/", {"base_url": None}, format="json")

    _refused(response, "base_url")


def test_a_built_in_model_refuses_a_plugin_s_endpoint_change_before_its_own_protection(client, providers):
    built_in = LLMModel.objects.create(name="built-in-gpt", llm_provider=providers[0], base_url=ACME_URL, org=None, is_custom=False)

    repointed = client.patch(f"/api/llm-models/{built_in.pk}/", {"base_url": ELSEWHERE}, format="json")
    renamed = client.patch(f"/api/llm-models/{built_in.pk}/", {"name": "renamed"}, format="json")

    _refused(repointed, "base_url")
    assert renamed.status_code == 403, renamed.content
    built_in.refresh_from_db()
    assert (built_in.name, built_in.base_url) == ("built-in-gpt", ACME_URL)


@pytest.mark.parametrize(
    "body",
    [{"base_url": ELSEWHERE}, {"deployment_id": "elsewhere"}, {"base_url": ELSEWHERE, "deployment_id": "elsewhere"}],
    ids=["url", "deployment", "both"],
)
def test_a_plugin_cannot_create_a_model_with_an_endpoint(client, providers, body):
    response = client.post("/api/llm-models/", {"name": "weather-gpt", "llm_provider": providers[0].pk, **body}, format="json")

    _refused(response, *body)
    assert not LLMModel.objects.filter(name="weather-gpt").exists()


def test_a_plugin_cannot_repoint_a_model_it_created(client, providers):
    created = client.post("/api/llm-models/", {"name": "weather-gpt", "llm_provider": providers[0].pk}, format="json")
    assert created.status_code == 201, created.content

    response = client.patch(f"/api/llm-models/{created.json()['id']}/", {"base_url": ELSEWHERE}, format="json")

    _refused(response, "base_url")
    assert LLMModel.objects.get(pk=created.json()["id"]).base_url is None


def test_the_name_provider_and_an_unchanged_endpoint_stay_editable(client, org_llm_model, providers):
    response = client.put(
        f"/api/llm-models/{org_llm_model.pk}/",
        {"name": "acme-gpt-renamed", "llm_provider": providers[1].pk, "base_url": ACME_URL, "description": "Renamed by the plugin"},
        format="json",
    )

    assert response.status_code == 200, response.content
    org_llm_model.refresh_from_db()
    assert (org_llm_model.name, org_llm_model.llm_provider, org_llm_model.base_url) == ("acme-gpt-renamed", providers[1], ACME_URL)


@pytest.mark.parametrize("field", ["base_url", "deployment"])
def test_an_embedding_model_s_endpoint_is_not_the_plugin_s_to_set(client, acme, providers, field):
    model = EmbeddingModel.objects.create(name="acme-embed", embedding_provider=providers[0], org=acme, is_custom=True)

    created = client.post("/api/embedding-models/", {"name": "weather-embed", "embedding_provider": providers[0].pk, field: "x"}, format="json")
    repointed = client.patch(f"/api/embedding-models/{model.pk}/", {field: "x"}, format="json")

    _refused(created, field)
    _refused(repointed, field)


def _authenticated_principal(raw_key):
    request = Request(
        APIRequestFactory().post("/", HTTP_AUTHORIZATION=f"PluginKey {raw_key}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    return request.user


@pytest.mark.parametrize(
    ("entity_type", "data"),
    [
        (EntityType.LLM_MODEL, {"name": "imported-gpt", "provider_name": "openai", "base_url": ELSEWHERE, "tags": []}),
        (EntityType.EMBEDDING_MODEL, {"name": "imported-embed", "provider_name": "openai", "deployment": "x", "tags": []}),
    ],
    ids=["llm", "embedding"],
)
def test_an_import_by_a_plugin_cannot_create_a_model_with_an_endpoint(acme_key, acme, providers, entity_type, data):
    principal = _authenticated_principal(acme_key)

    with pytest.raises(ValidationError):
        entity_registry.get_strategy(entity_type).create_entity(dict(data), None, org_id=acme.pk, user=principal)

    endpointless = {key: value for key, value in data.items() if key not in ("base_url", "deployment")}
    created = entity_registry.get_strategy(entity_type).create_entity(endpointless, None, org_id=acme.pk, user=principal)
    assert created.org_id == acme.pk


# ---- quickstart reuses an organization's model by name ----


def test_quickstart_reusing_a_plugin_s_model_sends_the_key_to_the_vendor(client, client_as, admin_acme, acme, providers):
    for url, body in (
        ("/api/llm-models/", {"name": "gpt-4o-mini", "llm_provider": providers[0].pk}),
        ("/api/embedding-models/", {"name": "text-embedding-3-small", "embedding_provider": providers[0].pk}),
    ):
        _refused(client.post(url, {**body, "base_url": ELSEWHERE}, format="json"), "base_url")
        assert client.post(url, body, format="json").status_code == 201
    person = client_as(admin_acme)
    person.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    response = person.post("/api/quickstart/", {"provider": "openai", "api_key": "sk-org-admin"}, format="json")

    assert response.status_code == 200, response.content
    llm_config = LLMConfig.objects.get(org=acme, custom_name=response.json()["config_name"])
    embedding_config = EmbeddingConfig.objects.get(org=acme, custom_name=response.json()["config_name"])
    assert (llm_config.model.name, llm_config.model.base_url, llm_config.model.deployment_id) == ("gpt-4o-mini", None, None)
    assert (embedding_config.model.base_url, embedding_config.model.deployment) == (None, None)


# ---- everyone else ----


def test_a_person_with_the_same_rights_still_sets_model_endpoints(acme, org_llm_model, providers, django_user_model):
    role = Role.objects.create(name="Model editor", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.LLM_CONFIGS.value, permissions=int(Permission.READ | Permission.CREATE | Permission.UPDATE)
    )
    person = django_user_model.objects.create_user(email="model-editor@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=person, org=acme, role=role)
    client = APIClient()
    client.force_authenticate(user=person)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    repointed = client.patch(f"/api/llm-models/{org_llm_model.pk}/", {"base_url": ELSEWHERE}, format="json")
    created = client.post("/api/llm-models/", {"name": "person-gpt", "llm_provider": providers[0].pk, "deployment_id": "d1"}, format="json")

    assert (repointed.status_code, created.status_code) == (200, 201), (repointed.content, created.content)


def test_a_plugin_in_another_organization_gets_not_found(plugin, service_account_key, beta, org_llm_model):
    beta_client = service_account_client(service_account_key(plugin, beta), beta)

    response = beta_client.patch(f"/api/llm-models/{org_llm_model.pk}/", {"name": "renamed"}, format="json")

    assert response.status_code == 404
    org_llm_model.refresh_from_db()
    assert org_llm_model.name == "acme-gpt"


# ---- the guard covers every model a secret-holding config points at ----

ENDPOINT_FIELD_NAMES = {"base_url", "deployment_id", "deployment"}
# Serializers that write an endpoint field without going through the guard, and why.
UNGUARDED_ON_PURPOSE = {
    # The import strategy checks the endpoint fields itself before it creates a row
    # (`test_an_import_by_a_plugin_cannot_create_a_model_with_an_endpoint`), and never
    # updates one: an existing model is reused when every field matches.
    "LLMModelImportSerializer",
    "EmbeddingModelImportSerializer",
}


def _models_secret_holding_configs_point_at():
    targets = set()
    for config in apps.get_models():
        if not any(getattr(field, "related_model", None) is Secret for field in config._meta.concrete_fields):
            continue
        for field in config._meta.concrete_fields:
            target = getattr(field, "related_model", None)
            if field.many_to_one and target not in (None, Secret):
                if ENDPOINT_FIELD_NAMES & {target_field.name for target_field in target._meta.concrete_fields}:
                    targets.add(target)
    return targets


def _write_serializers_of(model):
    from tables import urls  # noqa: F401  -- importing registers every serializer

    seen, stack = set(), [ModelSerializer]
    while stack:
        for subclass in stack.pop().__subclasses__():
            if subclass not in seen:
                seen.add(subclass)
                stack.append(subclass)
    return [
        serializer_class
        for serializer_class in seen
        if not serializer_class.__module__.startswith("tests.")
        and getattr(getattr(serializer_class, "Meta", None), "model", None) is model
    ]


def _guarded_endpoint_fields_by_serializer():
    from tables import urls  # noqa: F401  -- importing registers every viewset

    return {
        viewset.serializer_class.__name__: viewset.model_endpoint_fields
        for viewset in ModelEndpointsGuardedViewSetMixin.__subclasses__()
    }


def test_the_model_viewsets_guard_their_endpoint_fields():
    assert _guarded_endpoint_fields_by_serializer() == {
        "LLMModelSerializer": LLM_MODEL_ENDPOINT_FIELDS,
        "EmbeddingModelSerializer": EMBEDDING_MODEL_ENDPOINT_FIELDS,
    }


def test_every_endpoint_field_of_a_model_a_config_with_a_secret_uses_is_guarded():
    targets = _models_secret_holding_configs_point_at()
    guarded_by_serializer = _guarded_endpoint_fields_by_serializer()
    unguarded = []
    for model in targets:
        for serializer_class in _write_serializers_of(model):
            if serializer_class.__name__ in UNGUARDED_ON_PURPOSE:
                continue
            writable = {
                field.source for field in serializer_class().fields.values() if not field.read_only and field.source in ENDPOINT_FIELD_NAMES
            }
            guarded = set(guarded_by_serializer.get(serializer_class.__name__, ()))
            unguarded += [f"{serializer_class.__name__}.{source}" for source in sorted(writable - guarded)]

    assert {model._meta.label for model in targets} >= {"tables.LLMModel", "tables.EmbeddingModel"}
    assert unguarded == []
