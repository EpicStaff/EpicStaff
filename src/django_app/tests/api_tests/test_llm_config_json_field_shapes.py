"""LLMConfig's JSON values must have a shape their readers load: extra_headers is checked
by its own validator, settings such as stop by the model catalog."""

import pytest

from ai_models.models import LLMConfig, LLMModel, Provider
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def model(db):
    provider, _ = Provider.objects.get_or_create(name="openai")
    yield LLMModel.objects.create(name="gpt-4o", llm_provider=provider, predefined=True)


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    yield api_client


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body, message_start",
    [
        ({"extra_headers": {"X-Retry": 3}}, "extra_headers: "),
        ({"extra_headers": ["X-Retry"]}, "extra_headers: "),
        ({"parameters": {"stop": [1, 2]}}, "parameters: stop: "),
        ({"parameters": {"stop": {"a": 1}}}, "parameters: stop: "),
    ],
)
def test_malformed_value_is_rejected_on_create(client, model, body, message_start):
    response = client.post(
        "/api/llm-configs/", {"custom_name": "bad", "model": model.id, **body}, format="json"
    )

    assert response.status_code == 400
    assert response.data["message"].startswith(message_start), response.data
    assert not LLMConfig.objects.filter(custom_name="bad").exists()


@pytest.mark.django_db
def test_well_formed_values_are_stored_as_sent(client, model):
    response = client.post(
        "/api/llm-configs/",
        {
            "custom_name": "good",
            "model": model.id,
            "extra_headers": {"X-Trace": "1"},
            "parameters": {"logit_bias": {"50256": -100}, "stop": ["END"], "seed": None},
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    config = LLMConfig.objects.get(id=response.data["id"])
    assert config.extra_headers == {"X-Trace": "1"}
    assert config.parameters == {"logit_bias": {"50256": -100}, "stop": ["END"], "seed": None}
