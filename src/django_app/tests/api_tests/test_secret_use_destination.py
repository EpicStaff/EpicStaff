"""A config that carries a secret (an API-key secret or an `epicstaff_secret(<name>)`
header marker) sends it to its destination: the config's `base_url` and its model's
`base_url`. Pointing such a config, or a model one of them uses, at another host
needs secrets:USE. Writes that leave the destination where it is stay free.

An MCP tool sends its auth secret to its `transport`, so the same rule holds for it.

The Twilio channel's create, which updates the channel's existing row in place, is a
write path of its own and is covered here too, as is the MCP tool's PUT, which fills
fields missing from the body before it saves."""

import pytest

from rbac.models.enums import Permission, ResourceType
from tables.models import EmbeddingConfig, LLMConfig
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel
from tables.models.mcp_models import McpTool
from tables.models.realtime_models import OpenAIRealtimeConfig
from tables.models.webhook_models import RealtimeChannel, TwilioChannel
from tables.services.secrets import secret_service
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants
from tests.rbac_cross_org_fixtures import beta  # noqa: F401

GATEWAY_URL = "https://gateway.example.com/v1"
ATTACKER_URL = "https://attacker.example.com/v1"
MARKER_HEADERS = {"Authorization": "Bearer epicstaff_secret(GATEWAY_TOKEN)"}


@pytest.fixture
def no_use_client(db, django_user_model, default_org):
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="destination-nouse@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.LLM_CONFIGS.value: FULL_CRUD,
            ResourceType.VOICE.value: FULL_CRUD,
            ResourceType.TOOLS.value: FULL_CRUD,
        },
    )


@pytest.fixture
def use_client(db, django_user_model, default_org):
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="destination-use@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ | Permission.USE),
            ResourceType.LLM_CONFIGS.value: FULL_CRUD,
        },
    )


@pytest.fixture
def custom_llm_model(default_org, openai_provider):
    def _make(name, base_url):
        return LLMModel.objects.create(
            name=name,
            llm_provider=openai_provider,
            base_url=base_url,
            is_custom=True,
            org=default_org,
        )

    return _make


@pytest.fixture
def custom_embedding_model(default_org, openai_provider):
    def _make(name, base_url):
        return EmbeddingModel.objects.create(
            name=name,
            embedding_provider=openai_provider,
            base_url=base_url,
            is_custom=True,
            org=default_org,
        )

    return _make


@pytest.fixture
def gateway_llm_model(custom_llm_model):
    return custom_llm_model("gateway-llm", GATEWAY_URL)


@pytest.fixture
def secret_llm_config(default_org, gateway_llm_model, secret_a):
    return LLMConfig.objects.create(
        custom_name="destination-secret-config",
        model=gateway_llm_model,
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def secret_embedding_config(default_org, embedding_model, secret_a):
    return EmbeddingConfig.objects.create(
        custom_name="destination-secret-embedder",
        model=embedding_model,
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.mark.django_db
def test_llm_config_base_url_change_with_api_key_denied(no_use_client, secret_llm_config):
    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("base_url:")
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.base_url is None


@pytest.mark.django_db
def test_base_url_change_on_marker_only_config_denied(no_use_client, default_org):
    config = LLMConfig.objects.create(
        custom_name="destination-marker-config", extra_headers=MARKER_HEADERS, org=default_org
    )

    response = no_use_client.patch(
        f"/api/llm-configs/{config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("base_url:")
    config.refresh_from_db()
    assert config.base_url is None


@pytest.mark.django_db
def test_dropping_all_markers_while_changing_base_url_is_free(no_use_client, default_org):
    # Whether the config carries a secret is judged after the write: once this
    # request drops the only marker, nothing is sent to the new host.
    config = LLMConfig.objects.create(
        custom_name="destination-marker-dropped", extra_headers=MARKER_HEADERS, org=default_org
    )

    response = no_use_client.patch(
        f"/api/llm-configs/{config.pk}/",
        {"extra_headers": {}, "base_url": ATTACKER_URL},
        format="json",
    )

    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert config.extra_headers == {}
    assert config.base_url == ATTACKER_URL


@pytest.mark.django_db
def test_switch_to_custom_model_with_other_base_url_denied(
    no_use_client, secret_llm_config, gateway_llm_model, custom_llm_model
):
    attacker_model = custom_llm_model("attacker-llm", ATTACKER_URL)

    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"model": attacker_model.pk}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("model:")
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.model_id == gateway_llm_model.pk


@pytest.mark.django_db
def test_switch_to_model_with_same_base_url_is_free(
    no_use_client, secret_llm_config, custom_llm_model
):
    sibling_model = custom_llm_model("gateway-llm-sibling", GATEWAY_URL)

    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"model": sibling_model.pk}, format="json"
    )

    assert response.status_code == 200, response.json()
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.model_id == sibling_model.pk


@pytest.mark.django_db
def test_unrelated_field_edit_is_free(no_use_client, secret_llm_config):
    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"temperature": 0.9}, format="json"
    )

    assert response.status_code == 200, response.json()
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.temperature == 0.9


@pytest.mark.django_db
@pytest.mark.parametrize("stored, sent", [(None, ""), ("", None)])
def test_empty_and_null_base_url_are_same_destination(
    no_use_client, secret_llm_config, stored, sent
):
    LLMConfig.objects.filter(pk=secret_llm_config.pk).update(base_url=stored)

    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"base_url": sent}, format="json"
    )

    assert response.status_code == 200, response.json()
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.base_url == sent


@pytest.mark.django_db
def test_base_url_change_without_secret_is_free(no_use_client, default_org, gateway_llm_model):
    config = LLMConfig.objects.create(
        custom_name="destination-plain-config",
        model=gateway_llm_model,
        extra_headers={"X-Trace": "plain"},
        org=default_org,
    )

    response = no_use_client.patch(
        f"/api/llm-configs/{config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert config.base_url == ATTACKER_URL


@pytest.mark.django_db
@pytest.mark.parametrize(
    "secret_fields_for",
    [
        pytest.param(lambda secret: {"api_key_secret": secret}, id="api-key"),
        pytest.param(lambda secret: {"extra_headers": MARKER_HEADERS}, id="header-marker"),
    ],
)
def test_llm_model_base_url_edit_used_by_secret_config_denied(
    no_use_client, default_org, gateway_llm_model, secret_a, secret_fields_for
):
    LLMConfig.objects.create(
        custom_name="destination-model-user",
        model=gateway_llm_model,
        org=default_org,
        **secret_fields_for(secret_a),
    )

    response = no_use_client.patch(
        f"/api/llm-models/{gateway_llm_model.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("base_url:")
    gateway_llm_model.refresh_from_db()
    assert gateway_llm_model.base_url == GATEWAY_URL


@pytest.mark.django_db
def test_llm_model_base_url_edit_without_secret_configs_is_free(
    no_use_client, default_org, gateway_llm_model
):
    LLMConfig.objects.create(
        custom_name="destination-plain-model-user", model=gateway_llm_model, org=default_org
    )

    response = no_use_client.patch(
        f"/api/llm-models/{gateway_llm_model.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 200, response.json()
    gateway_llm_model.refresh_from_db()
    assert gateway_llm_model.base_url == ATTACKER_URL


@pytest.mark.django_db
def test_built_in_model_edit_stays_immutable_without_use(
    no_use_client, default_org, gpt_4o_llm, secret_a
):
    LLMConfig.objects.create(
        custom_name="destination-builtin-user",
        model=gpt_4o_llm,
        api_key_secret=secret_a,
        org=default_org,
    )

    response = no_use_client.patch(
        f"/api/llm-models/{gpt_4o_llm.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 403, response.json()
    gpt_4o_llm.refresh_from_db()
    assert gpt_4o_llm.base_url is None


@pytest.mark.django_db
def test_embedding_config_model_switch_denied(
    no_use_client, secret_embedding_config, embedding_model, custom_embedding_model
):
    attacker_model = custom_embedding_model("attacker-embedder", ATTACKER_URL)

    response = no_use_client.patch(
        f"/api/embedding-configs/{secret_embedding_config.pk}/",
        {"model": attacker_model.pk},
        format="json",
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("model:")
    secret_embedding_config.refresh_from_db()
    assert secret_embedding_config.model_id == embedding_model.pk


@pytest.mark.django_db
def test_embedding_model_base_url_edit_denied(
    no_use_client, default_org, custom_embedding_model, secret_a
):
    gateway_model = custom_embedding_model("gateway-embedder", GATEWAY_URL)
    EmbeddingConfig.objects.create(
        custom_name="destination-embedder-user",
        model=gateway_model,
        api_key_secret=secret_a,
        org=default_org,
    )

    response = no_use_client.patch(
        f"/api/embedding-models/{gateway_model.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("base_url:")
    gateway_model.refresh_from_db()
    assert gateway_model.base_url == GATEWAY_URL


@pytest.mark.django_db
def test_embedding_model_base_url_edit_without_secret_config_is_free(
    no_use_client, default_org, custom_embedding_model
):
    gateway_model = custom_embedding_model("gateway-embedder", GATEWAY_URL)
    EmbeddingConfig.objects.create(
        custom_name="destination-plain-embedder-user", model=gateway_model, org=default_org
    )

    response = no_use_client.patch(
        f"/api/embedding-models/{gateway_model.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 200, response.json()
    gateway_model.refresh_from_db()
    assert gateway_model.base_url == ATTACKER_URL


@pytest.mark.django_db
def test_holder_of_use_may_change_destination(
    use_client, secret_llm_config, gateway_llm_model, secret_embedding_config, custom_embedding_model
):
    attacker_embedder = custom_embedding_model("attacker-embedder", ATTACKER_URL)

    config_response = use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )
    model_response = use_client.patch(
        f"/api/llm-models/{gateway_llm_model.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )
    embedder_response = use_client.patch(
        f"/api/embedding-configs/{secret_embedding_config.pk}/",
        {"model": attacker_embedder.pk},
        format="json",
    )

    assert config_response.status_code == 200, config_response.json()
    assert model_response.status_code == 200, model_response.json()
    assert embedder_response.status_code == 200, embedder_response.json()
    secret_llm_config.refresh_from_db()
    gateway_llm_model.refresh_from_db()
    secret_embedding_config.refresh_from_db()
    assert secret_llm_config.base_url == ATTACKER_URL
    assert gateway_llm_model.base_url == ATTACKER_URL
    assert secret_embedding_config.model_id == attacker_embedder.pk


@pytest.fixture
def secret_b(default_org):
    return secret_service.create(text="sk-destination-b", org=default_org, name="DESTINATION_B")


@pytest.fixture
def twilio_channel(default_org, secret_a):
    channel = RealtimeChannel.objects.create(name="destination-twilio-channel", org=default_org)
    return TwilioChannel.objects.create(
        channel=channel, account_sid="AC_original", auth_token_secret=secret_a
    )


@pytest.mark.django_db
@pytest.mark.parametrize("secret_attribute", ["api_key_secret", "transcription_api_key_secret"])
def test_openai_realtime_base_url_change_with_secret_denied(
    no_use_client, default_org, secret_a, secret_attribute
):
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="destination-openai-realtime", org=default_org, **{secret_attribute: secret_a}
    )

    response = no_use_client.patch(
        f"/api/openai-realtime-configs/{config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("base_url:")
    config.refresh_from_db()
    assert config.base_url is None


@pytest.mark.django_db
def test_openai_realtime_base_url_change_without_secret_free(no_use_client, default_org):
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="destination-openai-realtime-plain", org=default_org
    )

    response = no_use_client.patch(
        f"/api/openai-realtime-configs/{config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert config.base_url == ATTACKER_URL


@pytest.mark.django_db
def test_twilio_upsert_existing_channel_secret_change_denied(
    no_use_client, twilio_channel, secret_a, secret_b
):
    response = no_use_client.post(
        "/api/twilio-channels/",
        {
            "channel": twilio_channel.pk,
            "account_sid": "AC_changed",
            "auth_token_secret_id": secret_b.pk,
        },
        format="json",
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("auth_token_secret_id:")
    twilio_channel.refresh_from_db()
    assert twilio_channel.auth_token_secret_id == secret_a.pk
    assert twilio_channel.account_sid == "AC_original"


@pytest.mark.django_db
def test_twilio_upsert_existing_channel_same_secret_is_free(
    no_use_client, twilio_channel, secret_a
):
    response = no_use_client.post(
        "/api/twilio-channels/",
        {
            "channel": twilio_channel.pk,
            "account_sid": "AC_changed",
            "auth_token_secret_id": secret_a.pk,
        },
        format="json",
    )

    assert response.status_code == 200, response.json()
    twilio_channel.refresh_from_db()
    assert twilio_channel.account_sid == "AC_changed"


@pytest.mark.django_db
def test_twilio_upsert_cross_org_channel_is_404_before_secret_check(no_use_client, beta, secret_b):
    beta_secret = secret_service.create(text="beta-token", org=beta, name="BETA_TWILIO_TOKEN")
    beta_channel = RealtimeChannel.objects.create(name="beta-twilio-channel", org=beta)
    beta_twilio = TwilioChannel.objects.create(
        channel=beta_channel, account_sid="AC_beta", auth_token_secret=beta_secret
    )

    response = no_use_client.post(
        "/api/twilio-channels/",
        {
            "channel": beta_channel.pk,
            "account_sid": "AC_hijacked",
            "auth_token_secret_id": secret_b.pk,
        },
        format="json",
    )

    assert response.status_code == 404, response.json()
    beta_twilio.refresh_from_db()
    assert beta_twilio.auth_token_secret_id == beta_secret.pk
    assert beta_twilio.account_sid == "AC_beta"


@pytest.mark.django_db
def test_child_viewset_cross_org_parent_is_404_before_secret_check_through_the_api(
    no_use_client, beta, secret_b
):
    # The beta channel has no Twilio row yet, so this create goes through the
    # viewset's perform_create rather than the upsert branch. Linking a secret on
    # create needs secrets:USE, so a secret check run before the parent check would
    # answer 400 and tell the caller the channel exists.
    beta_channel = RealtimeChannel.objects.create(name="beta-new-twilio-channel", org=beta)

    response = no_use_client.post(
        "/api/twilio-channels/",
        {
            "channel": beta_channel.pk,
            "account_sid": "AC_hijacked",
            "auth_token_secret_id": secret_b.pk,
        },
        format="json",
    )

    assert response.status_code == 404, response.json()
    assert not TwilioChannel.objects.filter(channel=beta_channel).exists()


MCP_SERVER_URL = "https://mcp.example.com/sse"
ATTACKER_MCP_URL = "https://attacker.example.com/sse"


@pytest.fixture
def secret_mcp_tool(default_org, secret_a):
    return McpTool.objects.create(
        name="destination-mcp-tool",
        transport=MCP_SERVER_URL,
        tool_name="search",
        auth_secret=secret_a,
        org=default_org,
    )


@pytest.mark.django_db
def test_mcp_transport_change_with_auth_secret_denied_patch(no_use_client, secret_mcp_tool):
    response = no_use_client.patch(
        f"/api/mcp-tools/{secret_mcp_tool.pk}/", {"transport": ATTACKER_MCP_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("transport:")
    secret_mcp_tool.refresh_from_db()
    assert secret_mcp_tool.transport == MCP_SERVER_URL


@pytest.mark.django_db
def test_mcp_transport_change_with_auth_secret_denied_put(no_use_client, secret_mcp_tool):
    # `auth_secret_id` is left out: PUT keeps the stored secret, so the tool still carries it.
    response = no_use_client.put(
        f"/api/mcp-tools/{secret_mcp_tool.pk}/",
        {"name": secret_mcp_tool.name, "transport": ATTACKER_MCP_URL, "tool_name": "search"},
        format="json",
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("transport:")
    secret_mcp_tool.refresh_from_db()
    assert secret_mcp_tool.transport == MCP_SERVER_URL


@pytest.mark.django_db
def test_put_with_same_transport_is_free(no_use_client, secret_mcp_tool, secret_a):
    response = no_use_client.put(
        f"/api/mcp-tools/{secret_mcp_tool.pk}/",
        {"name": secret_mcp_tool.name, "transport": MCP_SERVER_URL, "tool_name": "lookup"},
        format="json",
    )

    assert response.status_code == 200, response.json()
    secret_mcp_tool.refresh_from_db()
    assert secret_mcp_tool.tool_name == "lookup"
    assert secret_mcp_tool.auth_secret_id == secret_a.pk


@pytest.mark.django_db
def test_mcp_transport_change_without_auth_secret_free(no_use_client, default_org):
    tool = McpTool.objects.create(
        name="destination-plain-mcp-tool",
        transport=MCP_SERVER_URL,
        tool_name="search",
        org=default_org,
    )

    response = no_use_client.patch(
        f"/api/mcp-tools/{tool.pk}/", {"transport": ATTACKER_MCP_URL}, format="json"
    )

    assert response.status_code == 200, response.json()
    tool.refresh_from_db()
    assert tool.transport == ATTACKER_MCP_URL
