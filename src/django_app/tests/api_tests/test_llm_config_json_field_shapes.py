"""LLMConfig's stop, logit_bias and extra_headers must have a shape LLMConfigData loads."""

import pytest

from tables.models import LLMConfig, Provider
from tables.models.llm_models import LLMModel
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def model(db):
    provider, _ = Provider.objects.get_or_create(name="openai")
    yield LLMModel.objects.create(name="epicstaff-shape-model", llm_provider=provider)


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    yield api_client


def _error_field(response):
    # The project exception handler flattens field errors to "<field>: <message>".
    return response.data["message"].split(":", 1)[0]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field_name, value",
    [
        ("extra_headers", {"X-Retry": 3}),
        ("extra_headers", ["X-Retry"]),
        ("logit_bias", {"foo": 1}),
        ("logit_bias", {"50256": "high"}),
        ("stop", {"a": 1}),
        ("stop", [1, 2]),
    ],
)
def test_malformed_value_is_rejected_on_create(client, model, field_name, value):
    response = client.post(
        "/api/llm-configs/",
        {"custom_name": "bad", "model": model.id, field_name: value},
        format="json",
    )

    assert response.status_code == 400
    assert _error_field(response) == field_name
    assert not LLMConfig.objects.filter(custom_name="bad").exists()


@pytest.mark.django_db
def test_malformed_value_is_rejected_on_patch(client, acme, model):
    config = LLMConfig.objects.create(custom_name="c", model=model, org=acme)

    response = client.patch(
        f"/api/llm-configs/{config.id}/", {"extra_headers": {"X-Retry": 3}}, format="json"
    )

    assert response.status_code == 400
    assert _error_field(response) == "extra_headers"
    config.refresh_from_db()
    assert config.extra_headers == {}


@pytest.mark.django_db
def test_well_formed_values_are_stored_as_sent(client, model):
    response = client.post(
        "/api/llm-configs/",
        {
            "custom_name": "good",
            "model": model.id,
            "extra_headers": {"X-Trace": "1"},
            "logit_bias": {"50256": -100},
            "stop": ["END"],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    config = LLMConfig.objects.get(id=response.data["id"])
    assert config.extra_headers == {"X-Trace": "1"}
    assert config.logit_bias == {"50256": -100}
    assert config.stop == ["END"]


@pytest.mark.django_db
@pytest.mark.parametrize("field_name", ["stop", "logit_bias"])
def test_null_is_accepted(client, model, field_name):
    response = client.post(
        "/api/llm-configs/",
        {"custom_name": "nulls", "model": model.id, field_name: None},
        format="json",
    )

    assert response.status_code == 201, response.data
