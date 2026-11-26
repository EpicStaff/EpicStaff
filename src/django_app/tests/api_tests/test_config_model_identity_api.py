"""LLM and embedding config responses name their model by provider and model name, so a
client can show a config without loading the whole model list.

Presentation layer: the read side of `provider` / `model_name` lives in the shared config
serializer, tested through both config endpoints.
"""

import pytest
from ai_models.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

LLM = {
    "url": "/api/llm-configs/",
    "config": LLMConfig,
    "model": LLMModel,
    "provider_field": "llm_provider",
    # Two OpenAI models the committed catalog knows, so writes pass catalog validation.
    "catalog_names": ("gpt-4o", "gpt-6-luna"),
}
EMBEDDING = {
    "url": "/api/embedding-configs/",
    "config": EmbeddingConfig,
    "model": EmbeddingModel,
    "provider_field": "embedding_provider",
    "catalog_names": ("text-embedding-3-small", "text-embedding-3-large"),
}


@pytest.fixture(params=[LLM, EMBEDDING], ids=["llm", "embedding"])
def kind(request):
    return request.param


@pytest.fixture
def client(org_client_as, admin_acme, acme):
    return org_client_as(admin_acme, acme)


def _model(kind, provider_name, name, **fields):
    provider = Provider.objects.get_or_create(name=provider_name)[0]
    return kind["model"].objects.create(name=name, **{kind["provider_field"]: provider}, **fields)


def _config(kind, org, model, custom_name="config"):
    return kind["config"].objects.create(custom_name=custom_name, model=model, org=org)


def _identity(row):
    return row["provider"], row["model_name"]


@pytest.mark.parametrize("custom", [False, True], ids=["built-in", "custom"])
def test_detail_and_list_name_the_configs_model(client, acme, kind, custom):
    model = _model(kind, "openai", "gpt-6-luna", is_custom=custom, org=acme if custom else None)
    config = _config(kind, acme, model)

    detail = client.get(f"{kind['url']}{config.id}/")
    listed = client.get(kind["url"]).data["results"]

    assert detail.status_code == 200, detail.data
    assert (detail.data["model"], _identity(detail.data)) == (model.id, ("openai", "gpt-6-luna"))
    assert [_identity(row) for row in listed] == [("openai", "gpt-6-luna")]


def test_a_config_without_a_model_names_none(client, acme, kind):
    config = _config(kind, acme, model=None)

    response = client.get(f"{kind['url']}{config.id}/")

    assert response.status_code == 200, response.data
    assert (response.data["model"], _identity(response.data)) == (None, (None, None))


def test_a_model_without_a_provider_names_no_provider(client, acme, kind):
    model = kind["model"].objects.create(name="orphan-model")
    config = _config(kind, acme, model)

    response = client.get(f"{kind['url']}{config.id}/")

    assert _identity(response.data) == (None, "orphan-model")


def test_listing_runs_the_same_queries_for_one_config_and_for_many(client, acme, kind):
    def count_list_queries():
        with CaptureQueriesContext(connection) as captured:
            assert client.get(kind["url"]).status_code == 200
        return len(captured)

    _config(kind, acme, _model(kind, "openai", "first-model"), custom_name="config-0")
    # The first request also fills Django's content type cache: one query no later one runs.
    count_list_queries()
    one_config = count_list_queries()
    for number in range(1, 4):
        model = _model(kind, f"provider-{number}", f"model-{number}", is_custom=True, org=acme)
        _config(kind, acme, model, custom_name=f"config-{number}")

    assert count_list_queries() == one_config


def test_a_write_by_model_id_reads_back_the_stored_pair(client, kind):
    name = kind["catalog_names"][0]
    model = _model(kind, "openai", name, predefined=True)

    response = client.post(kind["url"], {"custom_name": "config", "model": model.id}, format="json")

    assert response.status_code == 201, response.data
    assert (response.data["model"], _identity(response.data)) == (model.id, ("openai", name))


def test_a_pair_resolves_as_before_and_reads_back_as_stored(client):
    # The pair is written by catalog name and alias; the stored rows carry other names.
    stored = _model(LLM, "google_ai", "gemini/gemini-2.5-flash", predefined=True)

    response = client.post(
        LLM["url"],
        {"custom_name": "config", "provider": "gemini", "model_name": "gemini-2.5-flash"},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["model"] == stored.id
    assert _identity(response.data) == ("google_ai", "gemini/gemini-2.5-flash")
    assert LLMConfig.objects.get(id=response.data["id"]).model_id == stored.id


def test_an_update_by_pair_repoints_the_config_and_reads_back_the_new_model(client, acme, kind):
    old_name, new_name = kind["catalog_names"]
    config = _config(kind, acme, _model(kind, "openai", old_name, predefined=True))
    new_model = _model(kind, "openai", new_name, predefined=True)

    response = client.patch(
        f"{kind['url']}{config.id}/", {"provider": "openai", "model_name": new_name}, format="json"
    )

    assert response.status_code == 200, response.data
    assert response.data["model"] == new_model.id
    assert _identity(response.data) == ("openai", new_name)
    config.refresh_from_db()
    assert config.model_id == new_model.id


@pytest.mark.parametrize("field_name", ["provider", "model_name"])
def test_a_null_half_of_the_pair_is_still_refused(client, kind, field_name):
    body = {"custom_name": "config", "provider": "openai", "model_name": kind["catalog_names"][0]}

    response = client.post(kind["url"], {**body, field_name: None}, format="json")

    assert response.status_code == 400
    assert not kind["config"].objects.exists()


# ---- a response sent back as a write ----


def _stored(config):
    config.refresh_from_db()
    return config.custom_name, config.model_id, config.parameters, config.connection


@pytest.mark.parametrize("with_model", [True, False], ids=["with-model", "without-model"])
def test_a_response_sent_back_as_a_put_succeeds_and_changes_nothing(
    client, acme, kind, with_model
):
    model = _model(kind, "openai", kind["catalog_names"][0], predefined=True)
    config = _config(kind, acme, model if with_model else None)
    before = _stored(config)
    read = client.get(f"{kind['url']}{config.id}/").data

    response = client.put(f"{kind['url']}{config.id}/", read, format="json")

    assert response.status_code == 200, response.data
    assert (response.data["model"], _identity(response.data)) == (read["model"], _identity(read))
    assert _stored(config) == before


def test_a_patch_renaming_a_config_with_the_pair_sent_back_succeeds(client, acme, kind):
    model = _model(kind, "openai", kind["catalog_names"][0], predefined=True)
    config = _config(kind, acme, model)
    read = client.get(f"{kind['url']}{config.id}/").data

    response = client.patch(
        f"{kind['url']}{config.id}/",
        {
            "custom_name": "renamed",
            "model": read["model"],
            "provider": read["provider"],
            "model_name": read["model_name"],
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    assert _stored(config)[:2] == ("renamed", model.id)


@pytest.mark.parametrize(
    "pair",
    [
        {"provider": "openai", "model_name": "another-model"},
        {"provider": "anthropic"},
        {"model_name": "another-model"},
        {"provider": None},
    ],
    ids=["other-name", "other-provider-only", "other-name-only", "null-provider"],
)
def test_model_and_a_pair_naming_another_model_get_400(client, acme, kind, pair):
    config = _config(kind, acme, _model(kind, "openai", kind["catalog_names"][0], predefined=True))
    before = _stored(config)

    response = client.patch(
        f"{kind['url']}{config.id}/", {"model": config.model_id, **pair}, format="json"
    )

    assert response.status_code == 400
    assert response.data["message"].startswith("model: ")
    assert _stored(config) == before
