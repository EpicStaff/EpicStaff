"""The OpenAI voice config's transcription model must be an OpenAI transcription model of
the model catalog."""

import pytest
from tables.models.realtime_models import OpenAIRealtimeConfig

from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

CONFIGS = "/api/openai-realtime-configs/"


@pytest.fixture
def client(org_client_as, admin_acme, acme):
    return org_client_as(admin_acme, acme)


def _create(client, transcription_model_name):
    # model_name is checked against the realtime registry; leave it at its default.
    return client.post(
        CONFIGS,
        {"custom_name": "voice", "transcription_model_name": transcription_model_name},
        format="json",
    )


@pytest.mark.parametrize("name", ["gpt-4o-transcribe", "whisper-1", None])
def test_catalog_transcription_model_or_none_is_accepted(client, name):
    response = _create(client, name)

    assert response.status_code == 201, response.data
    assert OpenAIRealtimeConfig.objects.get(id=response.data["id"]).transcription_model_name == name


@pytest.mark.parametrize("name", ["gpt-4o", "whisper-imaginary"])
def test_a_name_the_catalog_does_not_list_gets_400(client, name):
    response = _create(client, name)

    assert response.status_code == 400
    assert response.data["message"].startswith("transcription_model_name: ")


def test_a_stored_name_left_unchanged_still_saves(client, acme):
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="old", org=acme, transcription_model_name="whisper-legacy"
    )

    response = client.patch(
        f"{CONFIGS}{config.id}/",
        {"custom_name": "new", "transcription_model_name": "whisper-legacy"},
        format="json",
    )

    assert response.status_code == 200, response.data
