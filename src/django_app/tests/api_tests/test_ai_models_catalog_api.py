"""The read-only model catalog endpoints the config form reads.

The catalog is the same for every organization and holds no tenant data; the gate is
`llm_configs` read in the active organization. The model list also offers the active
organization's own custom models, never another organization's.
"""

from datetime import UTC, datetime

import pytest
from ai_models.domain.specs import ModelKind
from ai_models.models import EmbeddingModel, LLMModel, Provider
from ai_models.repository import CatalogRepository
from django.urls import reverse
from rbac.models.enums import Permission, ResourceType
from rest_framework import status
from rest_framework.test import APIClient

from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

PROVIDERS = reverse("ai-models-providers")
MODELS = reverse("ai-models-models")
SCHEMAS = reverse("ai-models-schemas")

ENDPOINT_QUERIES = [
    (PROVIDERS, {"kind": "llm"}),
    (MODELS, {"kind": "llm", "provider": "openai"}),
    (SCHEMAS, {"kind": "llm", "provider": "openai", "model": "gpt-4o"}),
]


@pytest.fixture
def viewer_client(org_client_as, viewer_only, acme):
    return org_client_as(viewer_only, acme)


@pytest.mark.parametrize(("url", "query"), ENDPOINT_QUERIES)
def test_llm_configs_read_is_enough(viewer_client, url, query):
    assert viewer_client.get(url, query).status_code == status.HTTP_200_OK


@pytest.mark.parametrize(("url", "query"), ENDPOINT_QUERIES)
def test_a_role_without_llm_configs_read_is_refused(custom_role_member, org_client_as, acme, url, query):
    user = custom_role_member(acme, {ResourceType.FLOWS: Permission.READ}, "flows-reader")

    assert org_client_as(user, acme).get(url, query).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize(("url", "query"), ENDPOINT_QUERIES)
def test_unauthenticated_is_refused(url, query):
    assert APIClient().get(url, query).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize(("url", "query"), ENDPOINT_QUERIES)
def test_a_non_member_of_the_active_org_is_refused(org_client_as, viewer_only, beta, url, query):
    assert org_client_as(viewer_only, beta).get(url, query).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize(("url", "query"), ENDPOINT_QUERIES)
def test_missing_org_header_is_refused(client_as, viewer_only, url, query):
    response = client_as(viewer_only).get(url, query)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "org_context_required"


def test_providers_list_shape_and_recommended_first(viewer_client):
    providers = viewer_client.get(PROVIDERS, {"kind": "llm"}).json()

    openai = next(provider for provider in providers if provider["name"] == "openai")
    assert openai == {"name": "openai", "label": "OpenAI", "recommended": True, "custom_models": True}
    recommended = [provider["recommended"] for provider in providers]
    assert recommended == sorted(recommended, reverse=True)


def test_embedding_lists_exactly_the_runtime_providers(viewer_client):
    providers = viewer_client.get(PROVIDERS, {"kind": "embedding"}).json()

    assert {provider["name"] for provider in providers} == {
        "openai",
        "gemini",
        "cohere",
        "mistral",
        "together_ai",
    }


def test_models_are_searchable(viewer_client):
    response = viewer_client.get(MODELS, {"kind": "llm", "provider": "openai", "search": "GPT-4O-MINI"})

    body = response.json()
    assert len(body) >= 1
    assert all("gpt-4o-mini" in model["name"] for model in body)
    assert set(body[0]) == {"name", "recommended", "deprecation_date", "limits", "custom", "is_favorite"}


def test_models_list_every_model_of_a_large_provider(viewer_client):
    expected = [model.name for model in CatalogRepository.default().models(ModelKind.LLM, "fireworks_ai")]

    body = viewer_client.get(MODELS, {"kind": "llm", "provider": "fireworks_ai"}).json()

    assert len(expected) > 50
    assert [model["name"] for model in body] == expected


def test_models_of_an_unknown_provider_are_empty(viewer_client):
    assert viewer_client.get(MODELS, {"kind": "llm", "provider": "nobody"}).json() == []


def test_schemas_return_parameters_connection_and_defaults(viewer_client):
    body = viewer_client.get(SCHEMAS, {"kind": "llm", "provider": "openai", "model": "gpt-4o"}).json()

    assert set(body) == {"parameters", "connection", "defaults"}
    assert body["parameters"]["additionalProperties"] is False
    assert body["parameters"]["properties"]["max_tokens"]["maximum"] == 16384
    assert "base_url" in body["connection"]["properties"]
    assert body["defaults"]["temperature"] == 0.7


def test_schemas_for_an_unknown_model_return_the_common_list(viewer_client):
    body = viewer_client.get(SCHEMAS, {"kind": "llm", "provider": "openai", "model": "my-fine-tune"}).json()

    common = CatalogRepository.default().provider("openai").common_parameters[ModelKind.LLM]
    assert list(body["parameters"]["properties"]) == list(common)


@pytest.mark.parametrize(
    ("url", "query", "field"),
    [
        (PROVIDERS, {}, "kind"),
        (PROVIDERS, {"kind": "chat"}, "kind"),
        (MODELS, {"kind": "llm"}, "provider"),
        (SCHEMAS, {"provider": "openai", "model": "gpt-4o"}, "kind"),
        (SCHEMAS, {"kind": "llm", "provider": "openai"}, "model"),
    ],
)
def test_missing_or_invalid_query_is_400_naming_the_field(viewer_client, url, query, field):
    response = viewer_client.get(url, query)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["message"].startswith(f"{field}: ")


def test_provider_rows_filter_by_kind_through_the_catalog(viewer_client):
    for name in ("openai", "google_ai", "voyage", "anthropic", "elevenlabs"):
        Provider.objects.create(name=name)

    def names(model_type):
        response = viewer_client.get("/api/providers/", {"model_type": model_type, "limit": 100})
        body = response.json()
        return {row["name"] for row in body.get("results", body)}

    # A row stored under an alias (google_ai for gemini) is one of the catalog's providers;
    # voyage has embedding models but does not run embedding.
    assert names("embedding") == {"openai", "google_ai"}
    assert names("llm") == {"openai", "google_ai", "anthropic"}


def _custom_model(model_class, org, provider_name, name, **fields):
    provider_field = "llm_provider" if model_class is LLMModel else "embedding_provider"
    provider, _ = Provider.objects.get_or_create(name=provider_name)
    return model_class.objects.create(org=org, name=name, is_custom=True, **{provider_field: provider}, **fields)


def _names(client, kind, provider, **query):
    return [model["name"] for model in client.get(MODELS, {"kind": kind, "provider": provider, **query}).json()]


@pytest.mark.parametrize(("model_class", "kind"), [(LLMModel, "llm"), (EmbeddingModel, "embedding")])
def test_models_list_the_orgs_custom_models_first(viewer_client, acme, model_class, kind):
    _custom_model(model_class, acme, "openai", "zeta-fine-tune")
    _custom_model(model_class, acme, "openai", "alpha-fine-tune")
    # The catalog follows, unchanged.
    catalog = [model.name for model in CatalogRepository.default().models(ModelKind(kind), "openai")]

    body = viewer_client.get(MODELS, {"kind": kind, "provider": "openai"}).json()

    assert body[:2] == [
        {
            "name": name,
            "recommended": False,
            "deprecation_date": None,
            "limits": {},
            "custom": True,
            "is_favorite": False,
        }
        for name in ("alpha-fine-tune", "zeta-fine-tune")
    ]
    assert [model["name"] for model in body[2:]] == catalog
    assert all(model["custom"] is False for model in body[2:])


def test_models_never_list_another_orgs_custom_models(viewer_client, acme, beta):
    _custom_model(LLMModel, acme, "openai", "acme-fine-tune")
    _custom_model(LLMModel, beta, "openai", "beta-fine-tune")

    names = _names(viewer_client, "llm", "openai")

    assert "acme-fine-tune" in names
    assert "beta-fine-tune" not in names


def test_models_leave_out_hidden_custom_models(viewer_client, acme):
    _custom_model(LLMModel, acme, "openai", "hidden-fine-tune", is_visible=False)

    assert "hidden-fine-tune" not in _names(viewer_client, "llm", "openai")


def test_search_matches_part_of_a_custom_name_ignoring_case(viewer_client, acme):
    _custom_model(LLMModel, acme, "openai", "Weather-Fine-Tune")
    _custom_model(LLMModel, acme, "openai", "billing-fine-tune")

    body = viewer_client.get(MODELS, {"kind": "llm", "provider": "openai", "search": "WEATHER"}).json()

    assert [model["name"] for model in body if model["custom"]] == ["Weather-Fine-Tune"]


def _custom_names(client, kind, provider):
    body = client.get(MODELS, {"kind": kind, "provider": provider}).json()
    return [model["name"] for model in body if model["custom"]]


# aleph_alpha takes custom models and its rows may be stored under its alias `aleph-alpha`.
@pytest.mark.parametrize("stored_provider", ["aleph_alpha", "aleph-alpha"])
def test_custom_models_are_listed_under_the_provider_name_and_its_alias(viewer_client, acme, stored_provider):
    _custom_model(LLMModel, acme, stored_provider, "luminous-tune")

    assert _custom_names(viewer_client, "llm", "aleph_alpha") == ["luminous-tune"]


def test_custom_models_stored_under_a_provider_alias_are_listed_once(viewer_client, acme):
    _custom_model(LLMModel, acme, "aleph-alpha", "luminous-tune")
    _custom_model(LLMModel, acme, "aleph_alpha", "luminous-tune")

    assert _custom_names(viewer_client, "llm", "aleph_alpha") == ["luminous-tune"]


def test_a_custom_row_naming_a_catalog_model_is_listed_once_as_the_catalog_model(viewer_client, acme):
    # Stored provider-prefixed, it is the catalog's gpt-4o under LiteLLM's lookup name.
    _custom_model(LLMModel, acme, "openai", "openai/gpt-4o")

    body = viewer_client.get(MODELS, {"kind": "llm", "provider": "openai", "search": "gpt-4o"}).json()

    assert [model for model in body if model["custom"]] == []
    assert [model["name"] for model in body].count("gpt-4o") == 1


def test_a_custom_row_naming_a_deprecated_catalog_model_is_not_listed(viewer_client, acme):
    today = datetime.now(UTC).date()
    deprecated = next(
        model.name
        for model in CatalogRepository.default().models(ModelKind.LLM, "openai", include_deprecated=True)
        if model.deprecation_date is not None and model.deprecation_date < today
    )
    _custom_model(LLMModel, acme, "openai", deprecated)

    assert deprecated not in _names(viewer_client, "llm", "openai", search=deprecated)


def test_a_provider_without_custom_models_lists_only_its_catalog(viewer_client, acme):
    _custom_model(LLMModel, acme, "google_ai", "my-gemini-tune")

    body = viewer_client.get(MODELS, {"kind": "llm", "provider": "gemini"}).json()

    assert body
    assert all(model["custom"] is False for model in body)

