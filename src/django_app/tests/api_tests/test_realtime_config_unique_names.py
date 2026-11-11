"""Realtime/voice provider configs: custom_name is unique per organization and per
provider table (case-sensitive). A duplicate is a clean 400 on `custom_name`, not a
DB IntegrityError."""

import pytest

from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

PROVIDERS = [
    pytest.param(
        OpenAIRealtimeConfig,
        "openai-realtime-configs",
        "An OpenAI realtime config with this name already exists.",
        id="openai",
    ),
    pytest.param(
        ElevenLabsRealtimeConfig,
        "elevenlabs-realtime-configs",
        "An ElevenLabs realtime config with this name already exists.",
        id="elevenlabs",
    ),
    pytest.param(
        GeminiRealtimeConfig,
        "gemini-realtime-configs",
        "A Gemini realtime config with this name already exists.",
        id="gemini",
    ),
]

OTHER_PROVIDER = {
    OpenAIRealtimeConfig: GeminiRealtimeConfig,
    ElevenLabsRealtimeConfig: OpenAIRealtimeConfig,
    GeminiRealtimeConfig: ElevenLabsRealtimeConfig,
}


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _list_url(route):
    return f"/api/{route}/"


def _detail_url(route, pk):
    return f"/api/{route}/{pk}/"


@pytest.mark.parametrize("model, route, message", PROVIDERS)
def test_duplicate_name_on_create_is_400_on_custom_name(acme_client, acme, model, route, message):
    model.objects.create(custom_name="dup", org=acme)

    response = acme_client.post(_list_url(route), {"custom_name": "dup"}, format="json")

    assert response.status_code == 400
    assert response.data["message"] == f"custom_name: {message}"
    assert model.objects.filter(org=acme, custom_name="dup").count() == 1


@pytest.mark.parametrize("model, route, message", PROVIDERS)
def test_name_differing_only_by_case_is_allowed(acme_client, acme, model, route, message):
    model.objects.create(custom_name="dup", org=acme)

    response = acme_client.post(_list_url(route), {"custom_name": "Dup"}, format="json")

    assert response.status_code == 201


@pytest.mark.parametrize("model, route, message", PROVIDERS)
def test_renaming_to_an_existing_name_is_400(acme_client, acme, model, route, message):
    model.objects.create(custom_name="taken", org=acme)
    config = model.objects.create(custom_name="mine", org=acme)

    response = acme_client.patch(
        _detail_url(route, config.pk), {"custom_name": "taken"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["message"] == f"custom_name: {message}"
    config.refresh_from_db()
    assert config.custom_name == "mine"


@pytest.mark.parametrize("model, route, message", PROVIDERS)
def test_saving_under_its_own_name_is_allowed(acme_client, acme, model, route, message):
    config = model.objects.create(custom_name="mine", org=acme)

    response = acme_client.patch(
        _detail_url(route, config.pk),
        {"custom_name": "mine"},
        format="json",
    )

    assert response.status_code == 200
    config.refresh_from_db()
    assert config.custom_name == "mine"


@pytest.mark.parametrize("model, route, message", PROVIDERS)
def test_same_name_in_a_different_provider_table_is_allowed(
    acme_client, acme, model, route, message
):
    OTHER_PROVIDER[model].objects.create(custom_name="dup", org=acme)

    response = acme_client.post(_list_url(route), {"custom_name": "dup"}, format="json")

    assert response.status_code == 201


@pytest.mark.parametrize("model, route, message", PROVIDERS)
def test_same_name_in_another_org_is_allowed(acme_client, beta, model, route, message):
    model.objects.create(custom_name="dup", org=beta)

    response = acme_client.post(_list_url(route), {"custom_name": "dup"}, format="json")

    assert response.status_code == 201
    assert model.objects.filter(custom_name="dup").count() == 2
