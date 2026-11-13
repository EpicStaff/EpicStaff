"""`timeout` of an LLM config saved through `/api/llm-configs/`.

Invariant: a timeout is either null (no timeout of its own) or a finite number of seconds
from 1 up to the deployment maximum (DJANGO_LLM_CONFIG_MAX_TIMEOUT), both ends included.
Anything else, NaN and Infinity included, is refused with 400 and nothing is stored.
"""

import pytest
from django.conf import settings

from tables.models import LLMConfig, Provider
from tables.models.llm_models import LLMModel
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

MAX_SECONDS = settings.LLM_CONFIG_TIMEOUT_MAX_SECONDS


@pytest.fixture
def model(db):
    provider, _ = Provider.objects.get_or_create(name="openai")
    yield LLMModel.objects.create(name="epicstaff-timeout-model", llm_provider=provider)


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
    "timeout",
    [1, MAX_SECONDS, None],
    ids=["minimum", "maximum", "null"],
)
def test_timeout_within_the_bounds_is_saved(client, model, timeout):
    response = client.post(
        "/api/llm-configs/",
        {"custom_name": "in-range", "model": model.id, "timeout": timeout},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert LLMConfig.objects.get(pk=response.data["id"]).timeout == timeout


@pytest.mark.django_db
@pytest.mark.parametrize(
    "timeout",
    [0.99, MAX_SECONDS + 0.01, "nan", "inf", "-inf"],
    ids=["below-minimum", "above-maximum", "nan", "infinity", "negative-infinity"],
)
def test_timeout_outside_the_bounds_is_refused_on_create(client, model, timeout):
    response = client.post(
        "/api/llm-configs/",
        {"custom_name": "out-of-range", "model": model.id, "timeout": timeout},
        format="json",
    )

    assert response.status_code == 400, response.data
    assert _error_field(response) == "timeout"
    assert not LLMConfig.objects.filter(custom_name="out-of-range").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("timeout", [0.99, MAX_SECONDS + 0.01], ids=["below", "above"])
def test_timeout_outside_the_bounds_is_refused_on_patch(client, acme, model, timeout):
    config = LLMConfig.objects.create(custom_name="kept", model=model, org=acme, timeout=60)

    response = client.patch(f"/api/llm-configs/{config.id}/", {"timeout": timeout}, format="json")

    assert response.status_code == 400, response.data
    assert _error_field(response) == "timeout"
    config.refresh_from_db()
    assert config.timeout == 60
