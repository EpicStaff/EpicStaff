"""The embedding config API on the model catalog: `parameters`, `connection`, and the model
a config names by provider and model name. Models come from the committed catalog."""

import pytest
from ai_models.models import EmbeddingConfig, EmbeddingModel, Provider

from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

CONFIGS = "/api/embedding-configs/"
MOVED = "Moved to parameters/connection."


def _provider(name):
    return Provider.objects.get_or_create(name=name)[0]


def _builtin(provider_name, name, **fields):
    return EmbeddingModel.objects.create(
        name=name, embedding_provider=_provider(provider_name), predefined=True, **fields
    )


@pytest.fixture
def gemini_embedding(db):
    # Stored bare under the alias row; the catalog key is `gemini/gemini-embedding-001`.
    return _builtin("google_ai", "gemini-embedding-001")


@pytest.fixture
def client(org_client_as, admin_acme, acme):
    return org_client_as(admin_acme, acme)


def _create(client, **body):
    return client.post(CONFIGS, {"custom_name": "embedder", **body}, format="json")


def test_create_without_parameters_stores_the_model_defaults(client, gemini_embedding):
    response = _create(client, model=gemini_embedding.id)

    assert response.status_code == 201, response.data
    assert response.data["parameters"] == {"task_type": "retrieval_document"}
    assert (response.data["needs_review"], response.data["review_reasons"]) == (False, [])
    assert EmbeddingConfig.objects.get(id=response.data["id"]).parameters == {
        "task_type": "retrieval_document"
    }


@pytest.mark.parametrize("field_name", ["task_type", "deployment", "base_url"])
def test_flat_field_gets_400_naming_it(client, gemini_embedding, field_name):
    response = _create(client, model=gemini_embedding.id, **{field_name: "x"})

    assert response.status_code == 400
    assert response.data["message"] == f"{field_name}: {MOVED}"


def test_unknown_parameter_gets_400(client, gemini_embedding):
    response = _create(client, model=gemini_embedding.id, parameters={"temperature": 0.2})

    assert response.status_code == 400
    assert response.data["message"].startswith("parameters: temperature: Not supported")


def test_invalid_settings_get_400_listing_each_field_by_dotted_path(client, gemini_embedding):
    response = _create(
        client,
        model=gemini_embedding.id,
        parameters={"task_type": "nonsense", "temperature": 0.2},
        connection={"base_url": 5},
    )

    assert response.status_code == 400
    assert response.data["message"].startswith("parameters: task_type: ")
    assert [(entry["field"], entry["value"]) for entry in response.data["errors"]] == [
        ("parameters.task_type", "nonsense"),
        ("parameters.temperature", 0.2),
        ("connection.base_url", 5),
    ]
    assert all(entry["reason"] for entry in response.data["errors"])


def test_rename_resending_a_stale_configs_unchanged_settings_saves(client, acme, gemini_embedding):
    config = EmbeddingConfig.objects.create(
        custom_name="old", model=gemini_embedding, org=acme, parameters={"task_type": "nonsense"}
    )

    response = client.patch(
        f"{CONFIGS}{config.id}/",
        {"custom_name": "new", "model": gemini_embedding.id, "parameters": {"task_type": "nonsense"}},
        format="json",
    )

    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert (config.custom_name, config.parameters) == ("new", {"task_type": "nonsense"})


def test_one_changed_setting_on_a_stale_config_gets_400(client, acme, gemini_embedding):
    config = EmbeddingConfig.objects.create(
        custom_name="old", model=gemini_embedding, org=acme, parameters={"task_type": "nonsense"}
    )

    response = client.patch(
        f"{CONFIGS}{config.id}/",
        {"parameters": {"task_type": "nonsense", "dimensions": 0}},
        format="json",
    )

    assert response.status_code == 400
    assert {entry["field"] for entry in response.data["errors"]} == {
        "parameters.task_type",
        "parameters.dimensions",
    }


def test_pair_resolves_the_predefined_row(client, gemini_embedding):
    response = _create(client, provider="gemini", model_name="gemini/gemini-embedding-001")

    assert response.status_code == 201, response.data
    assert response.data["model"] == gemini_embedding.id


def test_unknown_model_creates_the_orgs_custom_row(client, acme):
    _provider("openai")

    response = _create(client, provider="openai", model_name="my-embedder")

    assert response.status_code == 201, response.data
    custom = EmbeddingModel.objects.get(id=response.data["model"])
    assert (custom.org_id, custom.is_custom, custom.embedding_provider.name) == (acme.id, True, "openai")


def test_unknown_model_of_a_provider_without_custom_models_gets_400(client, gemini_embedding):
    response = _create(client, provider="gemini", model_name="gemini-imaginary")

    assert response.status_code == 400
    assert response.data["message"].startswith("model_name: ")
    assert EmbeddingModel.objects.count() == 1


def test_update_with_a_flat_field_gets_400(client, acme, gemini_embedding):
    config = EmbeddingConfig.objects.create(custom_name="c", model=gemini_embedding, org=acme)

    response = client.patch(f"{CONFIGS}{config.id}/", {"task_type": "x"}, format="json")

    assert response.status_code == 400
    assert response.data["message"] == f"task_type: {MOVED}"


def test_cross_org_config_404(client, beta, gemini_embedding):
    theirs = EmbeddingConfig.objects.create(custom_name="theirs", model=gemini_embedding, org=beta)

    assert client.get(f"{CONFIGS}{theirs.id}/").status_code == 404


def test_stale_config_needs_review(client, acme, gemini_embedding):
    config = EmbeddingConfig.objects.create(
        custom_name="c", model=gemini_embedding, org=acme, parameters={"task_type": "nonsense"}
    )

    data = client.get(f"{CONFIGS}{config.id}/").data

    assert data["needs_review"] is True
    assert data["review_reasons"][0].startswith("task_type: ")


@pytest.mark.parametrize("field_name", ["base_url", "deployment"])
def test_embedding_model_endpoint_field_gets_400(client, field_name):
    response = client.post(
        "/api/embedding-models/",
        {"name": "m", "embedding_provider": _provider("openai").id, field_name: "x"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["message"] == f"{field_name}: {MOVED}"
