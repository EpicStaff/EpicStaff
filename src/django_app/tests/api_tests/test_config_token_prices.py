"""Per-config token prices on LLM configs: stored as given, null by default,
non-negative, set together, and invisible across organizations."""

import pytest
from django.db import IntegrityError, transaction

from tables.models.llm_models import LLMConfig
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

LLM_CONFIGS = "/api/llm-configs/"


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


def _error_message(response) -> str:
    # The global exception handler folds field errors into the "message" string.
    return response.json()["message"]


@pytest.mark.django_db
def test_llm_config_prices_round_trip(client):
    created = client.post(
        LLM_CONFIGS,
        {
            "custom_name": "priced-llm",
            "input_cost_per_token": 0.0000025,
            "output_cost_per_token": 0.00001,
        },
        format="json",
    )

    assert created.status_code == 201, created.data
    assert created.data["input_cost_per_token"] == 0.0000025
    assert created.data["output_cost_per_token"] == 0.00001
    stored = LLMConfig.objects.get(pk=created.data["id"])
    assert (stored.input_cost_per_token, stored.output_cost_per_token) == (0.0000025, 0.00001)
    fetched = client.get(f"{LLM_CONFIGS}{created.data['id']}/")
    assert fetched.data["input_cost_per_token"] == 0.0000025
    assert fetched.data["output_cost_per_token"] == 0.00001


@pytest.mark.django_db
def test_prices_default_to_null(client):
    llm = client.post(LLM_CONFIGS, {"custom_name": "unpriced-llm"}, format="json")

    assert llm.status_code == 201, llm.data
    assert llm.data["input_cost_per_token"] is None
    assert llm.data["output_cost_per_token"] is None


@pytest.mark.django_db
def test_zero_prices_are_accepted(client):
    created = client.post(
        LLM_CONFIGS,
        {"custom_name": "free-llm", "input_cost_per_token": 0, "output_cost_per_token": 0},
        format="json",
    )

    assert created.status_code == 201, created.data
    assert created.data["input_cost_per_token"] == 0
    assert created.data["output_cost_per_token"] == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "prices, rejected_field",
    [
        ({"input_cost_per_token": -0.1, "output_cost_per_token": 0.1}, "input_cost_per_token"),
        ({"input_cost_per_token": 0.1, "output_cost_per_token": -0.1}, "output_cost_per_token"),
        ({"input_cost_per_token": "nan", "output_cost_per_token": 0.1}, "input_cost_per_token"),
    ],
    ids=["negative-input", "negative-output", "nan-input"],
)
def test_invalid_llm_price_is_rejected(client, prices, rejected_field):
    response = client.post(LLM_CONFIGS, {"custom_name": "bad-price", **prices}, format="json")

    assert response.status_code == 400
    assert rejected_field in _error_message(response)
    assert not LLMConfig.objects.filter(custom_name="bad-price").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "prices, missing_field",
    [
        ({"input_cost_per_token": 0.1}, "output_cost_per_token"),
        ({"output_cost_per_token": 0.1}, "input_cost_per_token"),
        ({"input_cost_per_token": 0.1, "output_cost_per_token": None}, "output_cost_per_token"),
    ],
    ids=["input-only", "output-only", "output-explicitly-null"],
)
def test_llm_config_with_only_one_price_is_rejected(client, prices, missing_field):
    response = client.post(LLM_CONFIGS, {"custom_name": "half-priced", **prices}, format="json")

    assert response.status_code == 400
    assert missing_field in _error_message(response)
    assert not LLMConfig.objects.filter(custom_name="half-priced").exists()


@pytest.mark.django_db
def test_patch_of_one_price_keeps_the_stored_other_one(client, acme):
    config = LLMConfig.objects.create(
        custom_name="patch-price",
        org=acme,
        input_cost_per_token=0.1,
        output_cost_per_token=0.2,
    )

    response = client.patch(
        f"{LLM_CONFIGS}{config.pk}/", {"input_cost_per_token": 0.3}, format="json"
    )

    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert (config.input_cost_per_token, config.output_cost_per_token) == (0.3, 0.2)


@pytest.mark.django_db
def test_patch_that_leaves_one_price_set_is_rejected(client, acme):
    config = LLMConfig.objects.create(custom_name="patch-unpriced", org=acme)

    response = client.patch(
        f"{LLM_CONFIGS}{config.pk}/", {"input_cost_per_token": 0.3}, format="json"
    )

    assert response.status_code == 400
    assert "output_cost_per_token" in _error_message(response)
    config.refresh_from_db()
    assert config.input_cost_per_token is None


@pytest.mark.django_db
def test_patch_clearing_both_prices_is_accepted(client, acme):
    config = LLMConfig.objects.create(
        custom_name="patch-clear",
        org=acme,
        input_cost_per_token=0.1,
        output_cost_per_token=0.2,
    )

    response = client.patch(
        f"{LLM_CONFIGS}{config.pk}/",
        {"input_cost_per_token": None, "output_cost_per_token": None},
        format="json",
    )

    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert config.input_cost_per_token is None
    assert config.output_cost_per_token is None


@pytest.mark.django_db
def test_patch_of_an_unrelated_field_on_an_unpriced_config_is_accepted(client, acme):
    config = LLMConfig.objects.create(custom_name="patch-other", org=acme)

    response = client.patch(f"{LLM_CONFIGS}{config.pk}/", {"temperature": 1.0}, format="json")

    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_another_orgs_llm_config_prices_are_not_readable_or_writable(client, beta):
    foreign = LLMConfig.objects.create(
        custom_name="beta-priced",
        org=beta,
        input_cost_per_token=0.1,
        output_cost_per_token=0.2,
    )

    assert client.get(f"{LLM_CONFIGS}{foreign.pk}/").status_code == 404
    patched = client.patch(
        f"{LLM_CONFIGS}{foreign.pk}/",
        {"input_cost_per_token": 0, "output_cost_per_token": 0},
        format="json",
    )
    assert patched.status_code == 404
    foreign.refresh_from_db()
    assert (foreign.input_cost_per_token, foreign.output_cost_per_token) == (0.1, 0.2)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "prices",
    [{"input_cost_per_token": 0.1}, {"output_cost_per_token": 0.1}],
    ids=["input-only", "output-only"],
)
def test_database_rejects_a_half_priced_llm_config(acme, prices):
    with pytest.raises(IntegrityError), transaction.atomic():
        LLMConfig.objects.create(custom_name="orm-half-priced", org=acme, **prices)

    assert not LLMConfig.objects.filter(custom_name="orm-half-priced").exists()
