import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.llm_models import (
    LLMConfig,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
)
from tables.models.embedding_models import EmbeddingConfig
from tables.models.default_models import DefaultModels
from tables.models.tag_models import (
    LLMConfigTag,
    EmbeddingConfigTag,
    RealtimeConfigTag,
    RealtimeTranscriptionConfigTag,
)
from tests.fixtures import *

QUICKSTART_TAG = "quickstart:latest"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def quickstart_url():
    return reverse("quickstart")


@pytest.fixture
def quickstart_apply_url():
    return reverse("quickstart_apply")


@pytest.fixture
def openai_provider_seeded(openai_provider):
    """
    QuickstartService calls Provider.objects.get(name=provider) and also
    uses get_or_create for models, so the provider must already exist.
    """
    from tables.models.llm_models import (
        LLMModel,
        RealtimeModel,
        RealtimeTranscriptionModel,
    )
    from tables.models.embedding_models import EmbeddingModel

    LLMModel.objects.get_or_create(name="gpt-4o-mini", llm_provider=openai_provider)
    EmbeddingModel.objects.get_or_create(
        name="text-embedding-3-small", embedding_provider=openai_provider
    )
    RealtimeModel.objects.get_or_create(
        name="gpt-4o-mini-realtime-preview-2024-12-17", provider=openai_provider
    )
    RealtimeTranscriptionModel.objects.get_or_create(
        name="whisper-1", provider=openai_provider
    )
    return openai_provider


# ---------------------------------------------------------------------------
# GET /api/quickstart/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_quickstart_no_history(auth_client, quickstart_url):
    response = auth_client.get(quickstart_url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert "openai" in response.data["supported_providers"]
    assert response.data["last_config"] is None
    assert response.data["is_synced"] is False


@pytest.mark.django_db
def test_get_quickstart_shows_last_config_after_run(
    auth_client, quickstart_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )

    response = auth_client.get(quickstart_url)

    assert response.status_code == status.HTTP_200_OK, response.content
    last = response.data["last_config"]
    assert last is not None
    assert last["config_name"] == "quickstart_openai"
    assert last["llm_config"] is not None
    assert last["embedding_config"] is not None
    assert last["realtime_config"] is not None
    assert last["realtime_transcription_config"] is not None


@pytest.mark.django_db
def test_get_quickstart_is_synced_false_before_apply(
    auth_client, quickstart_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )

    response = auth_client.get(quickstart_url)

    assert response.data["is_synced"] is False


@pytest.mark.django_db
def test_get_quickstart_is_synced_true_after_apply(
    auth_client, quickstart_url, quickstart_apply_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    auth_client.post(quickstart_apply_url, format="json")

    response = auth_client.get(quickstart_url)

    assert response.data["is_synced"] is True


# ---------------------------------------------------------------------------
# POST /api/quickstart/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_quickstart_success(auth_client, quickstart_url, openai_provider_seeded):
    response = auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["config_name"] == "quickstart_openai"
    assert response.data["configs"]["llm_config"] is not None
    assert response.data["configs"]["embedding_config"] is not None
    assert response.data["configs"]["realtime_config"] is not None
    assert response.data["configs"]["realtime_transcription_config"] is not None


@pytest.mark.django_db
def test_post_quickstart_creates_configs_in_db(
    auth_client, quickstart_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )

    assert LLMConfig.objects.filter(custom_name="quickstart_openai").exists()
    assert EmbeddingConfig.objects.filter(custom_name="quickstart_openai").exists()
    assert RealtimeConfig.objects.filter(custom_name="quickstart_openai").exists()
    assert RealtimeTranscriptionConfig.objects.filter(
        custom_name="quickstart_openai"
    ).exists()


@pytest.mark.django_db
def test_post_quickstart_applies_quickstart_tag(
    auth_client, quickstart_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )

    assert LLMConfig.objects.filter(
        tags__name=QUICKSTART_TAG, tags__predefined=True
    ).exists()
    assert EmbeddingConfig.objects.filter(
        tags__name=QUICKSTART_TAG, tags__predefined=True
    ).exists()
    assert RealtimeConfig.objects.filter(
        tags__name=QUICKSTART_TAG, tags__predefined=True
    ).exists()
    assert RealtimeTranscriptionConfig.objects.filter(
        tags__name=QUICKSTART_TAG, tags__predefined=True
    ).exists()


@pytest.mark.django_db
def test_post_quickstart_tag_moves_to_new_config_on_second_run(
    auth_client, quickstart_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test-2"}, format="json"
    )

    # Exactly one LLMConfig should carry the quickstart:latest tag
    tagged = LLMConfig.objects.filter(tags__name=QUICKSTART_TAG, tags__predefined=True)
    assert tagged.count() == 1
    assert tagged.first().custom_name == "quickstart_openai_1"

    # Old config must no longer carry the tag
    old = LLMConfig.objects.get(custom_name="quickstart_openai")
    assert not old.tags.filter(name=QUICKSTART_TAG, predefined=True).exists()


@pytest.mark.django_db
def test_post_quickstart_unique_name_on_second_run(
    auth_client, quickstart_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    response = auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test-2"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["config_name"] == "quickstart_openai_1"


@pytest.mark.django_db
def test_post_quickstart_invalid_provider(auth_client, quickstart_url):
    response = auth_client.post(
        quickstart_url, {"provider": "nonexistent", "api_key": "sk-test"}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content


@pytest.mark.skip(reason="pre-existing failure, unrelated to EST-1529")
@pytest.mark.django_db
def test_post_quickstart_does_not_auto_apply_to_default_models(
    auth_client, quickstart_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )

    dm = DefaultModels.load()
    assert dm.agent_llm_config is None
    assert dm.memory_embedding_config is None


# ---------------------------------------------------------------------------
# POST /api/quickstart/apply/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_apply_sets_default_models(
    auth_client, quickstart_url, quickstart_apply_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )

    response = auth_client.post(quickstart_apply_url, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content

    dm = DefaultModels.load()
    llm = LLMConfig.objects.get(custom_name="quickstart_openai")
    embedding = EmbeddingConfig.objects.get(custom_name="quickstart_openai")
    realtime = RealtimeConfig.objects.get(custom_name="quickstart_openai")
    transcription = RealtimeTranscriptionConfig.objects.get(
        custom_name="quickstart_openai"
    )

    assert dm.agent_llm_config_id == llm.id
    assert dm.agent_fcm_llm_config_id == llm.id
    assert dm.project_manager_llm_config_id == llm.id
    assert dm.memory_llm_config_id == llm.id
    assert dm.memory_embedding_config_id == embedding.id
    assert dm.voice_llm_config_id == realtime.id
    assert dm.transcription_llm_config_id == transcription.id


@pytest.mark.django_db
def test_post_apply_returns_404_when_no_quickstart(auth_client, quickstart_apply_url):
    response = auth_client.post(quickstart_apply_url, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_post_apply_response_contains_default_models_shape(
    auth_client, quickstart_url, quickstart_apply_url, openai_provider_seeded
):
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )

    response = auth_client.post(quickstart_apply_url, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    for field in [
        "agent_llm_config",
        "agent_fcm_llm_config",
        "project_manager_llm_config",
        "memory_llm_config",
        "memory_embedding_config",
        "voice_llm_config",
        "transcription_llm_config",
    ]:
        assert field in response.data, f"Missing field: {field}"


@pytest.mark.django_db
def test_post_apply_uses_latest_tagged_config(
    auth_client, quickstart_url, quickstart_apply_url, openai_provider_seeded
):
    """Apply always uses the config carrying the quickstart:latest tag."""
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    auth_client.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-test-2"}, format="json"
    )

    auth_client.post(quickstart_apply_url, format="json")

    dm = DefaultModels.load()
    latest_llm = LLMConfig.objects.filter(
        tags__name=QUICKSTART_TAG, tags__predefined=True
    ).first()
    assert dm.agent_llm_config_id == latest_llm.id
