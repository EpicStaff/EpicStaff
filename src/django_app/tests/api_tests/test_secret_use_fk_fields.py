"""Task 6a/6b: the eleven top-level FK serializers gate changes behind secrets:USE."""

import pytest
from rest_framework.test import APIClient

from tables.models import EmbeddingConfig, LLMConfig, Organization
from tables.models.embedding_models import EmbeddingModel
from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.llm_models import (
    LLMModel,
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from tables.models.mcp_models import McpTool
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)
from tables.models.webhook_models import RealtimeChannel, TwilioChannel
from tables.models.rbac_models import OrganizationUser, Role, RolePermission
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.secrets import secret_service


def _client_with(
    *, org: Organization, django_user_model, email: str, secrets_bitmask: int
):
    """An APIClient for a user whose custom role holds `secrets_bitmask` on secrets and full CRUD on llm_configs."""
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.SECRETS.value, permissions=secrets_bitmask
    )
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.LLM_CONFIGS.value,
        permissions=int(
            Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
        ),
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def no_use_client(db, django_user_model, default_org):
    return _client_with(
        org=default_org,
        django_user_model=django_user_model,
        email="fkuse_nouse@example.com",
        secrets_bitmask=int(Permission.READ),
    )


@pytest.fixture
def use_client(db, django_user_model, default_org):
    return _client_with(
        org=default_org,
        django_user_model=django_user_model,
        email="fkuse_use@example.com",
        secrets_bitmask=int(Permission.READ | Permission.USE),
    )


@pytest.fixture
def secret_a(default_org):
    return secret_service.create(
        text="sk-fkuse-a", org=default_org, name="FKUSE_SECRET_A"
    )


@pytest.fixture
def secret_b(default_org):
    return secret_service.create(
        text="sk-fkuse-b", org=default_org, name="FKUSE_SECRET_B"
    )


@pytest.fixture
def llm_config_pointing_at_secret_a(gpt_4o_llm, default_org, secret_a) -> LLMConfig:
    return LLMConfig.objects.create(
        custom_name="fkuse-llm-config",
        model=gpt_4o_llm,
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def embedding_config_pointing_at_secret_a(
    embedding_model, default_org, secret_a
) -> EmbeddingConfig:
    return EmbeddingConfig.objects.create(
        custom_name="fkuse-embedding-config",
        model=embedding_model,
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def realtime_config_pointing_at_secret_a(
    openai_realtime_model, default_org, secret_a
) -> RealtimeConfig:
    return RealtimeConfig.objects.create(
        custom_name="fkuse-realtime-config",
        realtime_model=openai_realtime_model,
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def realtime_transcription_config_pointing_at_secret_a(
    realtime_transcription_model, default_org, secret_a
) -> RealtimeTranscriptionConfig:
    return RealtimeTranscriptionConfig.objects.create(
        custom_name="fkuse-realtime-transcription-config",
        realtime_transcription_model=realtime_transcription_model,
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def elevenlabs_config_pointing_at_secret_a(
    default_org, secret_a
) -> ElevenLabsRealtimeConfig:
    return ElevenLabsRealtimeConfig.objects.create(
        custom_name="fkuse-elevenlabs-config",
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def gemini_config_pointing_at_secret_a(default_org, secret_a) -> GeminiRealtimeConfig:
    return GeminiRealtimeConfig.objects.create(
        custom_name="fkuse-gemini-config",
        api_key_secret=secret_a,
        org=default_org,
    )


#: (endpoint prefix, serializer field, name of a fixture that builds an instance
#: already pointing at `secret_a`). All six carry exactly one guarded field,
#: `api_key_secret_id`; the fixture name is resolved per-test via
#: `request.getfixturevalue` so each parametrized case gets a fresh instance.
GATED = [
    ("/api/llm-configs/", "api_key_secret_id", "llm_config_pointing_at_secret_a"),
    (
        "/api/embedding-configs/",
        "api_key_secret_id",
        "embedding_config_pointing_at_secret_a",
    ),
    (
        "/api/realtime-model-configs/",
        "api_key_secret_id",
        "realtime_config_pointing_at_secret_a",
    ),
    (
        "/api/realtime-transcription-model-configs/",
        "api_key_secret_id",
        "realtime_transcription_config_pointing_at_secret_a",
    ),
    (
        "/api/elevenlabs-realtime-configs/",
        "api_key_secret_id",
        "elevenlabs_config_pointing_at_secret_a",
    ),
    (
        "/api/gemini-realtime-configs/",
        "api_key_secret_id",
        "gemini_config_pointing_at_secret_a",
    ),
]


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint,field,fixture_name", GATED)
class TestFkFieldsAreGated:
    def test_changing_without_use_is_rejected(
        self, request, no_use_client, endpoint, field, fixture_name, secret_b
    ):
        instance = request.getfixturevalue(fixture_name)
        response = no_use_client.patch(
            f"{endpoint}{instance.id}/", {field: secret_b.id}, format="json"
        )
        assert response.status_code == 400, response.json()
        # The project's global exception handler (`utils.exception_handler.
        # custom_exception_handler`) flattens every DRF ValidationError into a
        # `{status_code, code, message}` envelope, folding the per-field detail
        # dict into the "message" string rather than keeping it as a top-level
        # key -- so the field name is asserted against "message", not the body.
        assert field in response.json()["message"]

    def test_resending_the_same_value_is_accepted(
        self, request, no_use_client, endpoint, field, fixture_name
    ):
        instance = request.getfixturevalue(fixture_name)
        current = getattr(instance, field)
        response = no_use_client.patch(
            f"{endpoint}{instance.id}/", {field: current}, format="json"
        )
        assert response.status_code == 200, response.json()

    def test_use_holder_can_change_the_value(
        self, request, use_client, endpoint, field, fixture_name, secret_b
    ):
        instance = request.getfixturevalue(fixture_name)
        response = use_client.patch(
            f"{endpoint}{instance.id}/", {field: secret_b.id}, format="json"
        )
        assert response.status_code == 200, response.json()


# ---------------------------------------------------------------------------
# Task 6b: OpenAIRealtimeConfigSerializer (two guarded fields), McpToolSerializer,
# TwilioChannelSerializer, TelegramTriggerNodeSerializer, and the quickstart
# serializer. `no_use_client`/`use_client` above only grant LLM_CONFIGS, so 6b
# builds its own clients that additionally cover VOICE (Twilio/RealtimeChannel),
# TOOLS (McpTool) and FLOWS (TelegramTriggerNode) -- each viewset's
# `rbac_resource_type`, verified against tables/views/model_view_sets.py.
# ---------------------------------------------------------------------------

_FULL_CRUD = int(
    Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
)


def _client_with_grants(
    *, org: Organization, django_user_model, email: str, resource_permissions: dict
):
    """An APIClient for a user whose custom role holds the given per-resource permission bitmasks."""
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    for resource_type, bitmask in resource_permissions.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=bitmask
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def no_use_client_6b(db, django_user_model, default_org):
    """Holds READ (not USE) on secrets, plus full CRUD on the resources 6b's five viewsets gate on."""
    return _client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="fkuse6b_nouse@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.LLM_CONFIGS.value: _FULL_CRUD,
            ResourceType.VOICE.value: _FULL_CRUD,
            ResourceType.TOOLS.value: _FULL_CRUD,
            ResourceType.FLOWS.value: _FULL_CRUD,
        },
    )


@pytest.fixture
def use_client_6b(db, django_user_model, default_org):
    """Holds READ + USE on secrets, plus full CRUD on the resources 6b's five viewsets gate on."""
    return _client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="fkuse6b_use@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ | Permission.USE),
            ResourceType.LLM_CONFIGS.value: _FULL_CRUD,
            ResourceType.VOICE.value: _FULL_CRUD,
            ResourceType.TOOLS.value: _FULL_CRUD,
            ResourceType.FLOWS.value: _FULL_CRUD,
        },
    )


@pytest.fixture
def mcp_tool_pointing_at_secret_a(default_org, secret_a) -> McpTool:
    return McpTool.objects.create(
        name="fkuse-mcp-tool",
        transport="https://example.com/mcp",
        tool_name="search",
        auth_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def openai_realtime_config_pointing_at_secret_a(
    default_org, secret_a
) -> OpenAIRealtimeConfig:
    return OpenAIRealtimeConfig.objects.create(
        custom_name="fkuse-openai-realtime-config",
        api_key_secret=secret_a,
        model_name="gpt-realtime-1.5",
        transcription_model_name="whisper-1",
        transcription_api_key_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def twilio_channel_pointing_at_secret_a(default_org, secret_a) -> TwilioChannel:
    channel = RealtimeChannel.objects.create(
        name="fkuse-realtime-channel", org=default_org
    )
    return TwilioChannel.objects.create(
        channel=channel,
        account_sid="AC" + "0" * 32,
        auth_token_secret=secret_a,
    )


@pytest.fixture
def telegram_trigger_node_pointing_at_secret_a(
    default_org, secret_a, mock_telegram_service
) -> TelegramTriggerNode:
    # mock_telegram_service: the model's post_save signal calls out to
    # TelegramTriggerService.register_telegram_trigger -- patched so building
    # this fixture (and PATCHing it below) never attempts a real network call.
    graph = Graph.objects.create(name="fkuse-telegram-graph", org=default_org)
    return TelegramTriggerNode.objects.create(
        node_name="fkuse-telegram-node",
        graph=graph,
        telegram_bot_api_key_secret=secret_a,
    )


#: (endpoint prefix, serializer field, name of a fixture that builds an
#: instance already pointing at `secret_a`). Five serializers, six rows --
#: OpenAIRealtimeConfigSerializer contributes two rows, one per guarded field,
#: since each is gated independently.
GATED_6B = [
    ("/api/mcp-tools/", "auth_secret_id", "mcp_tool_pointing_at_secret_a"),
    (
        "/api/openai-realtime-configs/",
        "api_key_secret_id",
        "openai_realtime_config_pointing_at_secret_a",
    ),
    (
        "/api/openai-realtime-configs/",
        "transcription_api_key_secret_id",
        "openai_realtime_config_pointing_at_secret_a",
    ),
    (
        "/api/twilio-channels/",
        "auth_token_secret_id",
        "twilio_channel_pointing_at_secret_a",
    ),
    (
        "/api/telegram-trigger-nodes/",
        "telegram_bot_api_key_secret_id",
        "telegram_trigger_node_pointing_at_secret_a",
    ),
]


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint,field,fixture_name", GATED_6B)
class TestFkFieldsAreGated6b:
    def test_changing_without_use_is_rejected(
        self, request, no_use_client_6b, endpoint, field, fixture_name, secret_b
    ):
        instance = request.getfixturevalue(fixture_name)
        # `.pk`, not `.id`: TwilioChannel's primary key is its `channel`
        # OneToOneField, so it has no `id` column.
        response = no_use_client_6b.patch(
            f"{endpoint}{instance.pk}/", {field: secret_b.id}, format="json"
        )
        assert response.status_code == 400, response.json()
        assert field in response.json()["message"]

    def test_resending_the_same_value_is_accepted(
        self, request, no_use_client_6b, endpoint, field, fixture_name
    ):
        instance = request.getfixturevalue(fixture_name)
        current = getattr(instance, field)
        response = no_use_client_6b.patch(
            f"{endpoint}{instance.pk}/", {field: current}, format="json"
        )
        assert response.status_code == 200, response.json()

    def test_use_holder_can_change_the_value(
        self, request, use_client_6b, endpoint, field, fixture_name, secret_b
    ):
        instance = request.getfixturevalue(fixture_name)
        response = use_client_6b.patch(
            f"{endpoint}{instance.pk}/", {field: secret_b.id}, format="json"
        )
        assert response.status_code == 200, response.json()


@pytest.mark.django_db
def test_changing_one_openai_field_names_only_that_field(
    no_use_client_6b, openai_realtime_config_pointing_at_secret_a, secret_a, secret_b
):
    """Changing api_key_secret_id while resending transcription_api_key_secret_id unchanged must name only the former."""
    config = openai_realtime_config_pointing_at_secret_a

    response = no_use_client_6b.patch(
        f"/api/openai-realtime-configs/{config.pk}/",
        {
            "api_key_secret_id": secret_b.id,
            "transcription_api_key_secret_id": secret_a.id,
        },
        format="json",
    )

    assert response.status_code == 400, response.json()
    body = response.json()["message"]
    assert "api_key_secret_id" in body
    assert "transcription_api_key_secret_id" not in body


@pytest.fixture
def quickstart_openai_seeded_6b(openai_provider):
    """The provider/model rows QuickstartService.quickstart() looks up for provider='openai', matching PROVIDER_CONFIGS' names (mirrors `openai_seeded` in test_quickstart_secret_reuse.py)."""
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


@pytest.mark.django_db
def test_quickstart_with_an_existing_secret_requires_use(
    no_use_client_6b, secret_a, openai_provider
):
    response = no_use_client_6b.post(
        "/api/quickstart/",
        {"provider": "openai", "api_key_secret_id": secret_a.id},
        format="json",
    )

    assert response.status_code == 400, response.json()
    assert "api_key_secret_id" in response.json()["message"]


@pytest.mark.django_db
def test_quickstart_with_an_existing_secret_and_use_succeeds(
    use_client_6b, secret_a, quickstart_openai_seeded_6b
):
    response = use_client_6b.post(
        "/api/quickstart/",
        {"provider": "openai", "api_key_secret_id": secret_a.id},
        format="json",
    )

    assert response.status_code == 200, response.json()


@pytest.mark.django_db
def test_quickstart_with_a_raw_api_key_is_unaffected(
    no_use_client_6b, quickstart_openai_seeded_6b
):
    """Creating with a raw api_key never changes an existing secret reference, so it needs no USE grant."""
    response = no_use_client_6b.post(
        "/api/quickstart/",
        {"provider": "openai", "api_key": "sk-fkuse-quickstart"},
        format="json",
    )

    assert response.status_code == 200, response.json()
