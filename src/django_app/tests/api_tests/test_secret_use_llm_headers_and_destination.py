"""secrets:USE gates which secrets an LLM config's header markers reach, and where a secret-bearing provider config sends its request.

For an LLM or embedding config the destination is its model's base_url (what
ConverterService sends to), so it moves by repointing the config's `model`, editing an
LLM config's own `base_url`, or editing the base_url of a custom model that
secret-bearing configs use. An OpenAI realtime config carries its own `base_url`.
"""

import pytest
from rbac.models.enums import Permission, ResourceType
from tables.models import EmbeddingConfig, LLMConfig
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel
from tables.models.provider import Provider
from tables.models.realtime_models import OpenAIRealtimeConfig
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants

ATTACKER_URL = "https://attacker.example"
MARKER_A = {"X-K": "epicstaff_secret(FKUSE_SECRET_A)"}
MARKER_B = {"X-K": "epicstaff_secret(HEADER_SECRET_B)"}


def _client(default_org, django_user_model, *, email, secrets_bitmask):
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email=email,
        resource_permissions={
            ResourceType.SECRETS.value: secrets_bitmask,
            ResourceType.LLM_CONFIGS.value: FULL_CRUD,
        },
    )


@pytest.fixture
def no_use_client(db, django_user_model, default_org):
    return _client(
        default_org,
        django_user_model,
        email="llmdest_nouse@example.com",
        secrets_bitmask=int(Permission.READ),
    )


@pytest.fixture
def use_client(db, django_user_model, default_org):
    return _client(
        default_org,
        django_user_model,
        email="llmdest_use@example.com",
        secrets_bitmask=int(Permission.READ | Permission.USE),
    )


@pytest.fixture
def attacker_model(default_org, openai_provider) -> LLMModel:
    return LLMModel.objects.create(
        name="exfil-model",
        llm_provider=openai_provider,
        base_url=ATTACKER_URL,
        org=default_org,
        is_custom=True,
    )


@pytest.fixture
def custom_model(default_org, openai_provider) -> LLMModel:
    return LLMModel.objects.create(
        name="proxy-model",
        llm_provider=openai_provider,
        base_url="https://proxy.internal.example",
        org=default_org,
        is_custom=True,
    )


@pytest.fixture
def other_builtin_model(anthropic_provider) -> LLMModel:
    """A catalog model of another provider with its own base_url: catalog rows are trusted alike."""
    return LLMModel.objects.create(
        name="claude-sonnet", llm_provider=anthropic_provider, base_url="https://catalog.example"
    )


@pytest.fixture
def anthropic_provider(db) -> Provider:
    return Provider.objects.get_or_create(name="anthropic")[0]


@pytest.fixture
def name_routed_model(default_org) -> LLMModel:
    """A custom model with no base_url whose name alone routes litellm to an attacker host.

    Created through the ORM: the API now rejects such a name, but rows written before
    that check, or by any path that skips the serializer, must still be gated.
    """
    return LLMModel.objects.create(
        name="huggingface/https://attacker.example",
        llm_provider=Provider.objects.get_or_create(name="huggingface")[0],
        base_url=None,
        org=default_org,
        is_custom=True,
    )


def _config(default_org, model, **fields) -> LLMConfig:
    return LLMConfig.objects.create(
        custom_name=fields.pop("custom_name", "llmdest-config"),
        model=model,
        org=default_org,
        **fields,
    )


def _assert_rejected_on(response, field):
    assert response.status_code == 400, response.json()
    # The global exception handler folds the per-field detail into "message" as
    # "<field>: <text>"; the text must be the secrets:USE denial, not another 400.
    message = response.json()["message"]
    assert f"{field}: " in message, message
    assert '"Use" permission on Secrets' in message, message


@pytest.mark.django_db
class TestHeaderMarkersOnCreate:
    def test_creating_with_a_marker_without_use_is_rejected(
        self, no_use_client, gpt_4o_llm
    ):
        response = no_use_client.post(
            "/api/llm-configs/",
            {"custom_name": "llmdest-new", "model": gpt_4o_llm.id, "extra_headers": MARKER_A},
            format="json",
        )

        _assert_rejected_on(response, "extra_headers")
        assert not LLMConfig.objects.filter(custom_name="llmdest-new").exists()

    def test_creating_with_a_marker_and_an_attacker_model_in_one_request_is_rejected(
        self, no_use_client, attacker_model
    ):
        response = no_use_client.post(
            "/api/llm-configs/",
            {
                "custom_name": "llmdest-exfil",
                "model": attacker_model.id,
                "extra_headers": MARKER_A,
            },
            format="json",
        )

        _assert_rejected_on(response, "extra_headers")
        assert not LLMConfig.objects.filter(custom_name="llmdest-exfil").exists()

    def test_creating_with_a_marker_with_use_succeeds(self, use_client, gpt_4o_llm):
        response = use_client.post(
            "/api/llm-configs/",
            {"custom_name": "llmdest-new", "model": gpt_4o_llm.id, "extra_headers": MARKER_A},
            format="json",
        )

        assert response.status_code == 201, response.json()
        assert LLMConfig.objects.get(custom_name="llmdest-new").extra_headers == MARKER_A

    def test_creating_with_plain_headers_without_use_succeeds(
        self, no_use_client, attacker_model
    ):
        response = no_use_client.post(
            "/api/llm-configs/",
            {
                "custom_name": "llmdest-plain",
                "model": attacker_model.id,
                "extra_headers": {"X-Trace": "1"},
            },
            format="json",
        )

        assert response.status_code == 201, response.json()


@pytest.mark.django_db
class TestHeaderMarkersOnUpdate:
    @pytest.mark.parametrize(
        "persisted,incoming",
        [
            ({}, MARKER_A),
            (MARKER_A, MARKER_B),
            (MARKER_A, {}),
        ],
        ids=["added", "changed", "removed"],
    )
    def test_changing_the_marker_names_without_use_is_rejected(
        self, no_use_client, default_org, gpt_4o_llm, persisted, incoming
    ):
        config = _config(default_org, gpt_4o_llm, extra_headers=persisted)

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/", {"extra_headers": incoming}, format="json"
        )

        _assert_rejected_on(response, "extra_headers")
        config.refresh_from_db()
        assert config.extra_headers == persisted

    def test_changing_the_marker_names_with_use_succeeds(
        self, use_client, default_org, gpt_4o_llm
    ):
        config = _config(default_org, gpt_4o_llm, extra_headers=MARKER_A)

        response = use_client.patch(
            f"/api/llm-configs/{config.id}/", {"extra_headers": MARKER_B}, format="json"
        )

        assert response.status_code == 200, response.json()
        config.refresh_from_db()
        assert config.extra_headers == MARKER_B

    def test_resending_the_same_markers_without_use_succeeds(
        self, no_use_client, default_org, gpt_4o_llm
    ):
        config = _config(default_org, gpt_4o_llm, extra_headers=MARKER_A)

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/",
            {"extra_headers": MARKER_A, "temperature": 0.9},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_adding_a_plain_header_beside_unchanged_markers_without_use_succeeds(
        self, no_use_client, default_org, gpt_4o_llm
    ):
        config = _config(default_org, gpt_4o_llm, extra_headers=MARKER_A)
        incoming = {**MARKER_A, "X-Trace": "1"}

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/", {"extra_headers": incoming}, format="json"
        )

        assert response.status_code == 200, response.json()
        config.refresh_from_db()
        assert config.extra_headers == incoming


@pytest.mark.django_db
class TestConfigDestination:
    @pytest.mark.parametrize("secret_kind", ["api_key_secret", "header_marker"])
    def test_repointing_a_secret_bearing_config_at_another_host_without_use_is_rejected(
        self, request, no_use_client, default_org, gpt_4o_llm, attacker_model, secret_kind
    ):
        if secret_kind == "api_key_secret":
            config = _config(
                default_org, gpt_4o_llm, api_key_secret=request.getfixturevalue("secret_a")
            )
        else:
            config = _config(default_org, gpt_4o_llm, extra_headers=MARKER_A)

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/", {"model": attacker_model.id}, format="json"
        )

        _assert_rejected_on(response, "model")
        config.refresh_from_db()
        assert config.model_id == gpt_4o_llm.id

    def test_repointing_a_secret_bearing_config_with_use_succeeds(
        self, use_client, llm_config_pointing_at_secret_a, attacker_model
    ):
        config = llm_config_pointing_at_secret_a

        response = use_client.patch(
            f"/api/llm-configs/{config.id}/", {"model": attacker_model.id}, format="json"
        )

        assert response.status_code == 200, response.json()

    def test_repointing_a_config_with_no_secret_without_use_succeeds(
        self, no_use_client, default_org, gpt_4o_llm, attacker_model
    ):
        config = _config(default_org, gpt_4o_llm, extra_headers={"X-Trace": "1"})

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/", {"model": attacker_model.id}, format="json"
        )

        assert response.status_code == 200, response.json()
        config.refresh_from_db()
        assert config.model_id == attacker_model.id

    def test_repointing_a_secret_bearing_config_at_another_builtin_model_succeeds(
        self, no_use_client, llm_config_pointing_at_secret_a, other_builtin_model
    ):
        config = llm_config_pointing_at_secret_a

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/",
            {"model": other_builtin_model.id},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_resending_the_same_model_on_a_secret_bearing_config_succeeds(
        self, no_use_client, llm_config_pointing_at_secret_a
    ):
        config = llm_config_pointing_at_secret_a

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/",
            {"model": config.model_id, "temperature": 0.9},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_changing_the_config_base_url_on_a_secret_bearing_config_without_use_is_rejected(
        self, no_use_client, llm_config_pointing_at_secret_a
    ):
        config = llm_config_pointing_at_secret_a

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/", {"base_url": ATTACKER_URL}, format="json"
        )

        _assert_rejected_on(response, "base_url")
        config.refresh_from_db()
        assert config.base_url is None

    def test_changing_the_config_base_url_on_a_config_with_no_secret_succeeds(
        self, no_use_client, default_org, gpt_4o_llm
    ):
        config = _config(default_org, gpt_4o_llm)

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/", {"base_url": ATTACKER_URL}, format="json"
        )

        assert response.status_code == 200, response.json()


@pytest.mark.django_db
class TestModelBaseUrl:
    @pytest.mark.parametrize("secret_kind", ["api_key_secret", "header_marker"])
    def test_changing_base_url_with_a_secret_bearing_dependent_without_use_is_rejected(
        self, request, no_use_client, default_org, custom_model, secret_kind
    ):
        if secret_kind == "api_key_secret":
            _config(default_org, custom_model, api_key_secret=request.getfixturevalue("secret_a"))
        else:
            _config(default_org, custom_model, extra_headers=MARKER_A)

        response = no_use_client.patch(
            f"/api/llm-models/{custom_model.id}/", {"base_url": ATTACKER_URL}, format="json"
        )

        _assert_rejected_on(response, "base_url")
        custom_model.refresh_from_db()
        assert custom_model.base_url == "https://proxy.internal.example"

    def test_changing_base_url_with_a_secret_bearing_dependent_with_use_succeeds(
        self, use_client, default_org, custom_model, secret_a
    ):
        _config(default_org, custom_model, api_key_secret=secret_a)

        response = use_client.patch(
            f"/api/llm-models/{custom_model.id}/", {"base_url": ATTACKER_URL}, format="json"
        )

        assert response.status_code == 200, response.json()

    def test_changing_base_url_without_dependents_succeeds(self, no_use_client, custom_model):
        response = no_use_client.patch(
            f"/api/llm-models/{custom_model.id}/", {"base_url": ATTACKER_URL}, format="json"
        )

        assert response.status_code == 200, response.json()
        custom_model.refresh_from_db()
        assert custom_model.base_url == ATTACKER_URL

    def test_changing_base_url_with_only_secretless_dependents_succeeds(
        self, no_use_client, default_org, custom_model
    ):
        _config(default_org, custom_model, extra_headers={"X-Trace": "1"})

        response = no_use_client.patch(
            f"/api/llm-models/{custom_model.id}/", {"base_url": ATTACKER_URL}, format="json"
        )

        assert response.status_code == 200, response.json()

    def test_editing_another_field_with_a_secret_bearing_dependent_succeeds(
        self, no_use_client, default_org, custom_model, secret_a
    ):
        _config(default_org, custom_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/llm-models/{custom_model.id}/",
            {"description": "renamed", "base_url": custom_model.base_url},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_creating_a_model_with_any_base_url_without_use_succeeds(
        self, no_use_client, openai_provider
    ):
        response = no_use_client.post(
            "/api/llm-models/",
            {"name": "new-exfil", "llm_provider": openai_provider.id, "base_url": ATTACKER_URL},
            format="json",
        )

        assert response.status_code == 201, response.json()


@pytest.mark.django_db
def test_putting_the_full_unchanged_payload_of_a_secret_bearing_config_without_use_succeeds(
    no_use_client, default_org, custom_model, secret_a
):
    """The frontend saves a config with PUT of the whole form; resending every reference unchanged needs no USE."""
    config = _config(
        default_org, custom_model, api_key_secret=secret_a, extra_headers=MARKER_A
    )
    payload = no_use_client.get(f"/api/llm-configs/{config.id}/").json()
    payload["temperature"] = 0.9

    response = no_use_client.put(f"/api/llm-configs/{config.id}/", payload, format="json")

    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert config.temperature == 0.9
    assert config.api_key_secret_id == secret_a.id
    assert config.extra_headers == MARKER_A
    assert config.model_id == custom_model.id


# ---------------------------------------------------------------------------
# Embedding configs: the API key goes to embedding_config.model.base_url.
# ---------------------------------------------------------------------------


@pytest.fixture
def custom_embedding_model(default_org, openai_provider) -> EmbeddingModel:
    return EmbeddingModel.objects.create(
        name="proxy-embedder",
        embedding_provider=openai_provider,
        base_url="https://proxy.internal.example",
        org=default_org,
        is_custom=True,
    )


@pytest.fixture
def attacker_embedding_model(default_org, openai_provider) -> EmbeddingModel:
    return EmbeddingModel.objects.create(
        name="exfil-embedder",
        embedding_provider=openai_provider,
        base_url=ATTACKER_URL,
        org=default_org,
        is_custom=True,
    )


def _embedding_config(default_org, model, **fields) -> EmbeddingConfig:
    return EmbeddingConfig.objects.create(
        custom_name="llmdest-embedding-config", model=model, org=default_org, **fields
    )


@pytest.mark.django_db
class TestEmbeddingConfigDestination:
    def test_repointing_a_key_bearing_config_at_another_host_without_use_is_rejected(
        self, no_use_client, default_org, embedding_model, attacker_embedding_model, secret_a
    ):
        config = _embedding_config(default_org, embedding_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/embedding-configs/{config.id}/",
            {"model": attacker_embedding_model.id},
            format="json",
        )

        _assert_rejected_on(response, "model")
        config.refresh_from_db()
        assert config.model_id == embedding_model.id

    def test_repointing_a_key_bearing_config_with_use_succeeds(
        self, use_client, default_org, embedding_model, attacker_embedding_model, secret_a
    ):
        config = _embedding_config(default_org, embedding_model, api_key_secret=secret_a)

        response = use_client.patch(
            f"/api/embedding-configs/{config.id}/",
            {"model": attacker_embedding_model.id},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_repointing_a_config_with_no_key_without_use_succeeds(
        self, no_use_client, default_org, embedding_model, attacker_embedding_model
    ):
        config = _embedding_config(default_org, embedding_model)

        response = no_use_client.patch(
            f"/api/embedding-configs/{config.id}/",
            {"model": attacker_embedding_model.id},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_resending_the_same_model_without_use_succeeds(
        self, no_use_client, default_org, embedding_model, secret_a
    ):
        config = _embedding_config(default_org, embedding_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/embedding-configs/{config.id}/",
            {"model": embedding_model.id, "api_key_secret_id": secret_a.id},
            format="json",
        )

        assert response.status_code == 200, response.json()


@pytest.mark.django_db
class TestEmbeddingModelBaseUrl:
    def test_changing_base_url_with_a_key_bearing_dependent_without_use_is_rejected(
        self, no_use_client, default_org, custom_embedding_model, secret_a
    ):
        _embedding_config(default_org, custom_embedding_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/embedding-models/{custom_embedding_model.id}/",
            {"base_url": ATTACKER_URL},
            format="json",
        )

        _assert_rejected_on(response, "base_url")
        custom_embedding_model.refresh_from_db()
        assert custom_embedding_model.base_url == "https://proxy.internal.example"

    def test_changing_base_url_with_a_key_bearing_dependent_with_use_succeeds(
        self, use_client, default_org, custom_embedding_model, secret_a
    ):
        _embedding_config(default_org, custom_embedding_model, api_key_secret=secret_a)

        response = use_client.patch(
            f"/api/embedding-models/{custom_embedding_model.id}/",
            {"base_url": ATTACKER_URL},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_changing_base_url_with_only_keyless_dependents_succeeds(
        self, no_use_client, default_org, custom_embedding_model
    ):
        _embedding_config(default_org, custom_embedding_model)

        response = no_use_client.patch(
            f"/api/embedding-models/{custom_embedding_model.id}/",
            {"base_url": ATTACKER_URL},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_resending_the_same_base_url_with_a_key_bearing_dependent_succeeds(
        self, no_use_client, default_org, custom_embedding_model, secret_a
    ):
        _embedding_config(default_org, custom_embedding_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/embedding-models/{custom_embedding_model.id}/",
            {"base_url": custom_embedding_model.base_url},
            format="json",
        )

        assert response.status_code == 200, response.json()


# ---------------------------------------------------------------------------
# OpenAI realtime configs: both API keys go to the config's own base_url. The other
# realtime configs (Gemini, ElevenLabs, the deprecated RealtimeConfig family) have no
# base_url, so they have no destination to move.
# ---------------------------------------------------------------------------


def _openai_realtime_config(default_org, **fields) -> OpenAIRealtimeConfig:
    return OpenAIRealtimeConfig.objects.create(
        custom_name="llmdest-openai-realtime",
        base_url="https://api.openai.com/v1",
        org=default_org,
        **fields,
    )


@pytest.mark.django_db
class TestOpenAIRealtimeConfigBaseUrl:
    @pytest.mark.parametrize("key_field", ["api_key_secret", "transcription_api_key_secret"])
    def test_changing_base_url_on_a_key_bearing_config_without_use_is_rejected(
        self, no_use_client, default_org, secret_a, key_field
    ):
        config = _openai_realtime_config(default_org, **{key_field: secret_a})

        response = no_use_client.patch(
            f"/api/openai-realtime-configs/{config.id}/",
            {"base_url": ATTACKER_URL},
            format="json",
        )

        _assert_rejected_on(response, "base_url")
        config.refresh_from_db()
        assert config.base_url == "https://api.openai.com/v1"

    def test_changing_base_url_on_a_key_bearing_config_with_use_succeeds(
        self, use_client, default_org, secret_a
    ):
        config = _openai_realtime_config(default_org, api_key_secret=secret_a)

        response = use_client.patch(
            f"/api/openai-realtime-configs/{config.id}/",
            {"base_url": ATTACKER_URL},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_changing_base_url_on_a_config_with_no_key_without_use_succeeds(
        self, no_use_client, default_org
    ):
        config = _openai_realtime_config(default_org)

        response = no_use_client.patch(
            f"/api/openai-realtime-configs/{config.id}/",
            {"base_url": ATTACKER_URL},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_resending_the_same_base_url_without_use_succeeds(
        self, no_use_client, default_org, secret_a
    ):
        config = _openai_realtime_config(default_org, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/openai-realtime-configs/{config.id}/",
            {"base_url": config.base_url, "voice_recognition_prompt": "hello"},
            format="json",
        )

        assert response.status_code == 200, response.json()


# ---------------------------------------------------------------------------
# The destination is the model's identity, not only its base_url: litellm also routes
# on the model name (a Hugging Face name starting with https:// becomes the endpoint),
# the provider, api_version and deployment.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConfigDestinationIsModelIdentity:
    def test_repointing_a_key_bearing_config_at_a_name_routed_custom_model_without_use_is_rejected(
        self, no_use_client, llm_config_pointing_at_secret_a, name_routed_model, gpt_4o_llm
    ):
        config = llm_config_pointing_at_secret_a

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/", {"model": name_routed_model.id}, format="json"
        )

        _assert_rejected_on(response, "model")
        config.refresh_from_db()
        assert config.model_id == gpt_4o_llm.id

    def test_repointing_a_key_bearing_config_at_a_name_routed_custom_model_with_use_succeeds(
        self, use_client, llm_config_pointing_at_secret_a, name_routed_model
    ):
        config = llm_config_pointing_at_secret_a

        response = use_client.patch(
            f"/api/llm-configs/{config.id}/", {"model": name_routed_model.id}, format="json"
        )

        assert response.status_code == 200, response.json()

    def test_switching_a_key_bearing_config_between_custom_models_without_use_is_rejected(
        self, no_use_client, default_org, custom_model, name_routed_model, secret_a
    ):
        config = _config(default_org, custom_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/llm-configs/{config.id}/", {"model": name_routed_model.id}, format="json"
        )

        _assert_rejected_on(response, "model")


@pytest.mark.django_db
class TestModelRoutingFields:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("name", "proxy-model-renamed"),
            ("api_version", "2099-01-01"),
            ("deployment_id", "other-deployment"),
            ("base_url", ATTACKER_URL),
        ],
    )
    def test_changing_a_routing_field_with_a_key_bearing_dependent_without_use_is_rejected(
        self, no_use_client, default_org, custom_model, secret_a, field, value
    ):
        _config(default_org, custom_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/llm-models/{custom_model.id}/", {field: value}, format="json"
        )

        _assert_rejected_on(response, field)

    def test_changing_the_provider_with_a_key_bearing_dependent_without_use_is_rejected(
        self, no_use_client, default_org, custom_model, secret_a, anthropic_provider
    ):
        _config(default_org, custom_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/llm-models/{custom_model.id}/",
            {"llm_provider": anthropic_provider.id},
            format="json",
        )

        _assert_rejected_on(response, "llm_provider")
        custom_model.refresh_from_db()
        assert custom_model.llm_provider.name == "openai"

    @pytest.mark.parametrize(
        "field,value",
        [
            ("name", "proxy-model-renamed"),
            ("api_version", "2099-01-01"),
            ("deployment_id", "other-deployment"),
        ],
    )
    def test_changing_a_routing_field_without_dependents_succeeds(
        self, no_use_client, custom_model, field, value
    ):
        response = no_use_client.patch(
            f"/api/llm-models/{custom_model.id}/", {field: value}, format="json"
        )

        assert response.status_code == 200, response.json()

    def test_changing_cosmetic_fields_with_a_key_bearing_dependent_succeeds(
        self, no_use_client, default_org, custom_model, secret_a
    ):
        _config(default_org, custom_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/llm-models/{custom_model.id}/",
            {"description": "notes", "is_visible": False},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_frontend_edit_payload_resent_unchanged_with_a_key_bearing_dependent_succeeds(
        self, no_use_client, default_org, custom_model, secret_a
    ):
        """The model dialog PATCHes name, base_url, deployment_id, api_version (blank as null) and is_visible."""
        _config(default_org, custom_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/llm-models/{custom_model.id}/",
            {
                "name": custom_model.name,
                "base_url": custom_model.base_url,
                "deployment_id": None,
                "api_version": None,
                "is_visible": False,
            },
            format="json",
        )

        assert response.status_code == 200, response.json()


@pytest.mark.django_db
class TestEmbeddingDestinationIsModelIdentity:
    def test_switching_a_key_bearing_config_between_builtin_models_succeeds(
        self, no_use_client, default_org, embedding_model, openai_provider, secret_a
    ):
        other_builtin = EmbeddingModel.objects.create(
            name="text-embedding-3-large",
            embedding_provider=openai_provider,
            base_url="https://catalog.example",
        )
        config = _embedding_config(default_org, embedding_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/embedding-configs/{config.id}/", {"model": other_builtin.id}, format="json"
        )

        assert response.status_code == 200, response.json()

    def test_repointing_a_key_bearing_config_at_a_custom_model_without_base_url_without_use_is_rejected(
        self, no_use_client, default_org, embedding_model, openai_provider, secret_a
    ):
        custom = EmbeddingModel.objects.create(
            name="huggingface/https://attacker.example",
            embedding_provider=openai_provider,
            org=default_org,
            is_custom=True,
        )
        config = _embedding_config(default_org, embedding_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/embedding-configs/{config.id}/", {"model": custom.id}, format="json"
        )

        _assert_rejected_on(response, "model")

    @pytest.mark.parametrize(
        "field,value", [("name", "proxy-embedder-renamed"), ("deployment", "other")]
    )
    def test_changing_a_routing_field_with_a_key_bearing_dependent_without_use_is_rejected(
        self, no_use_client, default_org, custom_embedding_model, secret_a, field, value
    ):
        _embedding_config(default_org, custom_embedding_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/embedding-models/{custom_embedding_model.id}/", {field: value}, format="json"
        )

        _assert_rejected_on(response, field)

    def test_changing_the_provider_with_a_key_bearing_dependent_without_use_is_rejected(
        self, no_use_client, default_org, custom_embedding_model, secret_a, anthropic_provider
    ):
        _embedding_config(default_org, custom_embedding_model, api_key_secret=secret_a)

        response = no_use_client.patch(
            f"/api/embedding-models/{custom_embedding_model.id}/",
            {"embedding_provider": anthropic_provider.id},
            format="json",
        )

        _assert_rejected_on(response, "embedding_provider")

    @pytest.mark.parametrize(
        "field,value", [("name", "proxy-embedder-renamed"), ("deployment", "other")]
    )
    def test_changing_a_routing_field_without_dependents_succeeds(
        self, no_use_client, custom_embedding_model, field, value
    ):
        response = no_use_client.patch(
            f"/api/embedding-models/{custom_embedding_model.id}/", {field: value}, format="json"
        )

        assert response.status_code == 200, response.json()


# ---------------------------------------------------------------------------
# Second layer: a model name can never carry a URL.
# ---------------------------------------------------------------------------

URL_NAME = "huggingface/https://attacker.example"


def _assert_url_name_rejected(response):
    assert response.status_code == 400, response.json()
    assert 'cannot contain "://"' in response.json()["message"]


@pytest.mark.django_db
class TestModelNameCannotCarryAUrl:
    def test_creating_an_llm_model_with_a_url_name_is_rejected(self, use_client, openai_provider):
        response = use_client.post(
            "/api/llm-models/",
            {"name": URL_NAME, "llm_provider": openai_provider.id},
            format="json",
        )

        _assert_url_name_rejected(response)
        assert not LLMModel.objects.filter(name=URL_NAME).exists()

    def test_renaming_an_llm_model_to_a_url_name_is_rejected(self, use_client, custom_model):
        response = use_client.patch(
            f"/api/llm-models/{custom_model.id}/", {"name": URL_NAME}, format="json"
        )

        _assert_url_name_rejected(response)

    def test_creating_an_embedding_model_with_a_url_name_is_rejected(
        self, use_client, openai_provider
    ):
        response = use_client.post(
            "/api/embedding-models/",
            {"name": URL_NAME, "embedding_provider": openai_provider.id},
            format="json",
        )

        _assert_url_name_rejected(response)
        assert not EmbeddingModel.objects.filter(name=URL_NAME).exists()

    def test_renaming_an_embedding_model_to_a_url_name_is_rejected(
        self, use_client, custom_embedding_model
    ):
        response = use_client.patch(
            f"/api/embedding-models/{custom_embedding_model.id}/",
            {"name": URL_NAME},
            format="json",
        )

        _assert_url_name_rejected(response)

    @pytest.mark.parametrize("name", ["openrouter/anthropic/claude-3.5-sonnet", "gpt-4o"])
    def test_provider_prefixed_names_without_a_url_are_accepted(
        self, use_client, openai_provider, name
    ):
        response = use_client.post(
            "/api/llm-models/",
            {"name": name, "llm_provider": openai_provider.id},
            format="json",
        )

        assert response.status_code == 201, response.json()
