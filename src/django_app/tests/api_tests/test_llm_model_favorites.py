"""Per-user favorite LLM models: `ai-models/favorite/` and `is_favorite` in the model list.

The config form names a model by provider and catalog name, so its star does too; the
star itself points at the model row a config of that name would use.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rbac.access.gates import IsPerson
from rbac.models import OrganizationUser
from rbac.models.enums import Permission, ResourceType
from rest_framework.test import APIClient

from ai_models.models import EmbeddingModel, LLMModel, LLMModelFavorite, Provider
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

MODELS = reverse("ai-models-models")
FAVORITE = reverse("ai-models-favorite")


def _favorite_url(model: str, provider: str = "openai") -> str:
    return f"{FAVORITE}?provider={provider}&model={model}"


def _favorites(client: APIClient, provider: str = "openai", kind: str = "llm") -> set[str]:
    response = client.get(MODELS, {"kind": kind, "provider": provider})
    assert response.status_code == 200, response.content
    return {model["name"] for model in response.json() if model["is_favorite"]}


def _provider(name: str) -> Provider:
    return Provider.objects.get_or_create(name=name)[0]


def _built_in(name: str, provider: str = "openai", **fields) -> LLMModel:
    return LLMModel.objects.create(
        name=name, llm_provider=_provider(provider), predefined=True, is_custom=False, **fields
    )


def _custom(org, name: str, provider: str = "openai") -> LLMModel:
    return LLMModel.objects.create(
        name=name, llm_provider=_provider(provider), org=org, is_custom=True
    )


@pytest.fixture
def gpt_4o():
    return _built_in("gpt-4o")


@pytest.fixture
def member_client(org_client_as, member_only, acme):
    return org_client_as(member_only, acme)


@pytest.fixture
def second_member(django_user_model, acme, role_member):
    user = django_user_model.objects.create_user(
        email="second-member-xorg@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.fixture
def system_key_client(issue_api_key, acme):
    raw_key, _ = issue_api_key(user=None, name="llm-favorites-system-key")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def test_a_starred_model_is_listed_as_a_favorite(member_client, member_only, gpt_4o):
    response = member_client.post(_favorite_url("gpt-4o"))

    assert response.status_code == 200, response.content
    assert _favorites(member_client) == {"gpt-4o"}
    assert LLMModelFavorite.objects.filter(user=member_only, llm_model=gpt_4o).exists()


@pytest.mark.parametrize("model_name", ["gpt-4o", "acme-fine-tune"])
def test_favorite_is_idempotent_both_ways_and_leaves_the_model_unchanged(
    member_client, member_only, acme, gpt_4o, model_name
):
    model = gpt_4o if model_name == "gpt-4o" else _custom(acme, model_name)
    model_row_before = LLMModel.objects.filter(pk=model.pk).values().get()

    added = [member_client.post(_favorite_url(model_name)) for _ in range(2)]
    favorites_after_adding = LLMModelFavorite.objects.filter(user=member_only).count()
    listed_after_adding = _favorites(member_client)
    removed = [member_client.delete(_favorite_url(model_name)) for _ in range(2)]

    assert [response.status_code for response in added + removed] == [200] * 4
    assert favorites_after_adding == 1
    assert listed_after_adding == {model_name}
    assert not LLMModelFavorite.objects.filter(user=member_only).exists()
    assert LLMModel.objects.filter(pk=model.pk).values().get() == model_row_before


def test_a_starred_custom_model_is_listed_as_a_favorite(member_client, acme):
    _custom(acme, "acme-fine-tune")

    member_client.post(_favorite_url("acme-fine-tune"))
    body = member_client.get(MODELS, {"kind": "llm", "provider": "openai"}).json()

    starred = [model for model in body if model["is_favorite"]]
    assert [(model["name"], model["custom"]) for model in starred] == [("acme-fine-tune", True)]


def test_a_row_stored_under_another_name_is_starred_and_listed_as_its_catalog_model(
    member_client, member_only
):
    # Stored provider-prefixed, the row is the catalog's gpt-4o under LiteLLM's lookup name.
    prefixed = _built_in("openai/gpt-4o")

    member_client.post(_favorite_url("gpt-4o"))
    listed = _favorites(member_client)
    member_client.delete(_favorite_url("gpt-4o"))

    assert listed == {"gpt-4o"}
    assert not LLMModelFavorite.objects.filter(user=member_only, llm_model=prefixed).exists()


def test_a_model_starred_under_a_provider_alias_is_listed_under_the_provider(member_client, acme):
    # aleph_alpha takes custom models, and its rows may be stored under its alias `aleph-alpha`.
    _custom(acme, "luminous-tune", provider="aleph-alpha")

    response = member_client.post(_favorite_url("luminous-tune", provider="aleph-alpha"))

    assert response.status_code == 200, response.content
    assert _favorites(member_client, provider="aleph_alpha") == {"luminous-tune"}


def test_favorites_are_per_user(member_client, org_client_as, second_member, acme, gpt_4o):
    member_client.post(_favorite_url("gpt-4o"))

    assert _favorites(member_client) == {"gpt-4o"}
    assert _favorites(org_client_as(second_member, acme)) == set()


def test_favorites_of_another_provider_are_not_listed(member_client, gpt_4o):
    _built_in("claude-sonnet-4-5", provider="anthropic")

    response = member_client.post(_favorite_url("claude-sonnet-4-5", provider="anthropic"))

    assert response.status_code == 200, response.content
    assert _favorites(member_client, provider="anthropic") == {"claude-sonnet-4-5"}
    assert _favorites(member_client) == set()


def test_embedding_models_are_never_favorites(member_client, acme, gpt_4o):
    member_client.post(_favorite_url("gpt-4o"))
    EmbeddingModel.objects.create(
        name="gpt-4o", embedding_provider=_provider("openai"), org=acme, is_custom=True
    )

    assert _favorites(member_client, kind="embedding") == set()


@pytest.mark.parametrize(
    ("model_name", "provider"),
    [
        ("no-such-model", "gemini"),  # gemini takes no custom models
        ("never-saved-fine-tune", "openai"),  # a custom name no config saved yet
        ("gpt-4o", "no-such-provider"),
    ],
)
def test_starring_a_model_without_a_stored_row_is_404_and_stores_nothing(
    member_client, gpt_4o, model_name, provider
):
    model_rows_before = LLMModel.objects.count()

    response = member_client.post(_favorite_url(model_name, provider=provider))

    assert response.status_code == 404, response.content
    assert response.json()["code"] == "not_found"
    assert not LLMModelFavorite.objects.exists()
    assert LLMModel.objects.count() == model_rows_before


def test_starring_another_orgs_custom_model_is_404_and_stores_nothing(member_client, beta):
    _custom(beta, "beta-fine-tune")

    response = member_client.post(_favorite_url("beta-fine-tune"))

    assert response.status_code == 404, response.content
    assert not LLMModelFavorite.objects.exists()


def test_another_orgs_favorites_are_neither_listed_nor_removed(
    member_client, org_client_as, member_only, beta, role_member
):
    # The caller also belongs to Beta and starred Beta's model while working there.
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)
    beta_model = _custom(beta, "beta-fine-tune")
    org_client_as(member_only, beta).post(_favorite_url("beta-fine-tune"))

    listed_in_acme = _favorites(member_client)
    response = member_client.delete(_favorite_url("beta-fine-tune"))

    assert listed_in_acme == set()
    assert response.status_code == 200, response.content
    assert LLMModelFavorite.objects.filter(user=member_only, llm_model=beta_model).exists()
    assert _favorites(org_client_as(member_only, beta)) == {"beta-fine-tune"}


def test_listing_costs_the_same_queries_however_many_models_are_favorites(
    member_client, member_only, gpt_4o
):
    def star(name: str) -> None:
        LLMModelFavorite.objects.create(user=member_only, llm_model=_built_in(name))

    def list_query_count() -> int:
        with CaptureQueriesContext(connection) as queries:
            _favorites(member_client)
        return len(queries)

    star("gpt-4o-mini")
    # Unmeasured: whatever the first request caches must not count for either side.
    _favorites(member_client)
    with_one_favorite = list_query_count()
    star("gpt-4.1")
    star("o3")
    with_three_favorites = list_query_count()

    assert with_three_favorites == with_one_favorite


@pytest.mark.parametrize(("grants", "expected_status"), [(Permission.READ, 200), (None, 403)])
def test_starring_needs_llm_configs_read(
    custom_role_member, org_client_as, acme, gpt_4o, grants, expected_status
):
    permissions = {ResourceType.FLOWS: Permission.READ}
    if grants is not None:
        permissions[ResourceType.LLM_CONFIGS] = grants
    user = custom_role_member(acme, permissions, f"favorites-{expected_status}")

    response = org_client_as(user, acme).post(_favorite_url("gpt-4o"))

    assert response.status_code == expected_status, response.content
    assert LLMModelFavorite.objects.filter(user=user).exists() is (expected_status == 200)


def test_the_system_key_lists_every_model_as_not_favorite(
    system_key_client, member_client, gpt_4o
):
    member_client.post(_favorite_url("gpt-4o"))

    assert _favorites(system_key_client) == set()


@pytest.mark.parametrize("method", ["post", "delete"])
def test_the_system_key_cannot_set_or_clear_a_favorite(system_key_client, gpt_4o, method):
    response = getattr(system_key_client, method)(_favorite_url("gpt-4o"))

    assert response.status_code == 403, response.content
    assert response.json()["message"] == IsPerson.message
    assert not LLMModelFavorite.objects.exists()


@pytest.mark.parametrize(
    ("query", "field"),
    [("?model=gpt-4o", "provider"), ("?provider=openai", "model")],
)
def test_a_missing_name_is_400_naming_the_field(member_client, query, field):
    response = member_client.post(f"{FAVORITE}{query}")

    assert response.status_code == 400, response.content
    assert response.json()["message"].startswith(f"{field}: ")
