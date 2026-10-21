"""A plugin may change where a model sends requests only on models it created.

The organization's configs send their keys to the endpoint of the model they use. A plugin
that could repoint an organization's model would receive those keys, so its endpoint fields
(the URL, the provider) are the plugin's to change only on its own rows.
"""

import pytest
from django.apps import apps
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rest_framework.relations import RelatedField
from rest_framework.serializers import ModelSerializer
from rest_framework.test import APIClient
from tables.models import Provider, Secret
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel, RealtimeModel, RealtimeTranscriptionModel
from tables.serializers.utils.secret_destination_guard_mixin import SecretDestinationGuardMixin

from tests.plugins_tests.conftest import service_account_client

pytestmark = [pytest.mark.django_db]

REFUSED = "This credential can change where requests are sent only on models it created"
ACCESS = [{"resource_type": "llm_configs", "actions": ["read", "create", "update"], "reason": "Its models."}]
ACME_URL = "https://llm.acme.example"
ELSEWHERE = "https://elsewhere.example"


@pytest.fixture
def plugin(weather_backend):
    return weather_backend(access=ACCESS)


@pytest.fixture
def client(plugin, service_account_key, acme):
    return service_account_client(service_account_key(plugin, acme), acme)


@pytest.fixture
def providers(db):
    return [Provider.objects.get_or_create(name=name)[0] for name in ("openai", "azure")]


@pytest.fixture
def org_llm_model(acme, providers):
    return LLMModel.objects.create(name="acme-gpt", llm_provider=providers[0], base_url=ACME_URL, org=acme, is_custom=True)


def _refused(response, field):
    assert response.status_code == 400, response.content
    message = response.json()["message"]
    assert field in message and REFUSED in message


# ---- the organization's models ----


def test_repointing_an_org_model_with_patch_is_refused(client, org_llm_model):
    response = client.patch(f"/api/llm-models/{org_llm_model.pk}/", {"base_url": ELSEWHERE}, format="json")

    _refused(response, "base_url")
    org_llm_model.refresh_from_db()
    assert org_llm_model.base_url == ACME_URL


def test_repointing_an_org_model_with_put_is_refused(client, org_llm_model, providers):
    response = client.put(
        f"/api/llm-models/{org_llm_model.pk}/",
        {"name": "acme-gpt", "llm_provider": providers[0].pk, "base_url": ELSEWHERE},
        format="json",
    )

    _refused(response, "base_url")
    org_llm_model.refresh_from_db()
    assert org_llm_model.base_url == ACME_URL


def test_moving_an_org_model_to_another_provider_is_refused(client, org_llm_model, providers):
    response = client.patch(f"/api/llm-models/{org_llm_model.pk}/", {"llm_provider": providers[1].pk}, format="json")

    _refused(response, "llm_provider")


def test_other_fields_of_an_org_model_and_an_unchanged_endpoint_stay_editable(client, org_llm_model, providers):
    response = client.put(
        f"/api/llm-models/{org_llm_model.pk}/",
        {"name": "acme-gpt", "llm_provider": providers[0].pk, "base_url": ACME_URL, "description": "Renamed by the plugin"},
        format="json",
    )

    assert response.status_code == 200, response.content


def test_repointing_an_org_embedding_model_is_refused(client, acme, providers):
    model = EmbeddingModel.objects.create(name="acme-embed", embedding_provider=providers[0], base_url=ACME_URL, org=acme, is_custom=True)

    response = client.patch(f"/api/embedding-models/{model.pk}/", {"base_url": ELSEWHERE}, format="json")

    _refused(response, "base_url")


@pytest.mark.parametrize(
    ("url", "model_class"),
    [("/api/realtime-models/", RealtimeModel), ("/api/realtime-transcription-models/", RealtimeTranscriptionModel)],
    ids=["realtime", "transcription"],
)
def test_moving_an_org_voice_model_to_another_provider_is_refused(client, acme, providers, url, model_class):
    model = model_class.objects.create(name="acme-voice", provider=providers[0], org=acme, is_custom=True)

    response = client.patch(f"{url}{model.pk}/", {"provider": providers[1].pk}, format="json")

    _refused(response, "provider")


# ---- its own models ----


def test_a_plugin_repoints_a_model_it_created(client, providers):
    created = client.post("/api/llm-models/", {"name": "weather-gpt", "llm_provider": providers[0].pk, "base_url": ACME_URL}, format="json")
    assert created.status_code == 201, created.content

    patched = client.patch(f"/api/llm-models/{created.json()['id']}/", {"base_url": ELSEWHERE}, format="json")
    put = client.put(
        f"/api/llm-models/{created.json()['id']}/",
        {"name": "weather-gpt", "llm_provider": providers[1].pk, "base_url": ACME_URL},
        format="json",
    )

    assert (patched.status_code, put.status_code) == (200, 200), (patched.content, put.content)
    assert LLMModel.objects.get(pk=created.json()["id"]).llm_provider == providers[1]


# ---- everyone else ----


def test_a_person_with_the_same_rights_still_repoints_org_models(acme, org_llm_model, django_user_model):
    role = Role.objects.create(name="Model editor", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.LLM_CONFIGS.value, permissions=int(Permission.READ | Permission.CREATE | Permission.UPDATE)
    )
    person = django_user_model.objects.create_user(email="model-editor@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=person, org=acme, role=role)
    client = APIClient()
    client.force_authenticate(user=person)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    response = client.patch(f"/api/llm-models/{org_llm_model.pk}/", {"base_url": ELSEWHERE}, format="json")

    assert response.status_code == 200, response.content


def test_a_plugin_in_another_organization_gets_not_found(plugin, service_account_key, beta, org_llm_model):
    beta_client = service_account_client(service_account_key(plugin, beta), beta)

    response = beta_client.patch(f"/api/llm-models/{org_llm_model.pk}/", {"base_url": ELSEWHERE}, format="json")

    assert response.status_code == 404
    org_llm_model.refresh_from_db()
    assert org_llm_model.base_url == ACME_URL


# ---- the guard covers every model a secret-holding config points at ----

# Serializers that write an endpoint field but never change an existing row, and why.
NEVER_UPDATE = {
    # The import creates new rows only: an existing model is reused when every field
    # matches (`find_existing`), never updated, and a row the plugin creates is its own.
    "LLMModelImportSerializer",
    "EmbeddingModelImportSerializer",
    "RealtimeModelImportSerializer",
    "RealtimeTranscriptionModelImportSerializer",
}


def _endpoint_fields(model):
    """The fields that decide where a model row sends requests: its URL and its provider."""
    return {
        field.name
        for field in model._meta.concrete_fields
        if field.name == "base_url" or getattr(field, "related_model", None) is Provider
    }


def _models_secret_holding_configs_point_at():
    targets = set()
    for config in apps.get_models():
        if not any(getattr(field, "related_model", None) is Secret for field in config._meta.concrete_fields):
            continue
        for field in config._meta.concrete_fields:
            target = getattr(field, "related_model", None)
            if field.many_to_one and target is not None and target is not Secret and _endpoint_fields(target):
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


def test_every_endpoint_field_of_a_model_a_config_with_a_secret_uses_is_guarded():
    targets = _models_secret_holding_configs_point_at()
    unguarded = []
    for model in targets:
        for serializer_class in _write_serializers_of(model):
            if serializer_class.__name__ in NEVER_UPDATE:
                continue
            serializer = serializer_class()
            writable = {
                field.source
                for field in serializer.fields.values()
                if not field.read_only and field.source in _endpoint_fields(model)
                and (isinstance(field, RelatedField) or field.source == "base_url")
            }
            guarded = set(serializer_class.secret_destination_fields) if issubclass(serializer_class, SecretDestinationGuardMixin) else set()
            unguarded += [f"{serializer_class.__name__}.{source}" for source in sorted(writable - guarded)]

    assert {model._meta.label for model in targets} >= {
        "tables.LLMModel",
        "tables.EmbeddingModel",
        "tables.RealtimeModel",
        "tables.RealtimeTranscriptionModel",
    }
    assert unguarded == []
