"""The read-only model catalog endpoints the config form reads.

The catalog is the same for every organization and holds no tenant data, so the only
gate is `llm_configs` read in the active organization.
"""

import pytest
from ai_models.domain.specs import ModelKind
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


def test_models_are_paginated_and_searchable(viewer_client):
    response = viewer_client.get(MODELS, {"kind": "llm", "provider": "openai", "search": "GPT-4O-MINI", "limit": 2})

    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] >= 1 and len(body["results"]) <= 2
    assert all("gpt-4o-mini" in model["name"] for model in body["results"])
    assert set(body["results"][0]) == {"name", "recommended", "deprecation_date", "limits"}


def test_models_of_an_unknown_provider_are_empty(viewer_client):
    assert viewer_client.get(MODELS, {"kind": "llm", "provider": "nobody"}).json()["count"] == 0


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
    from ai_models.models import Provider

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
