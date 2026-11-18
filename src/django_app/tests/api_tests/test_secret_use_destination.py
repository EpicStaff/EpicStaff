"""A model config that carries a secret (an API-key secret, or an `epicstaff_secret(<name>)`
marker in its `extra_headers` or `connection`) sends it to its destination: the fields of
its `connection` the catalog marks as endpoints (a base URL, an Azure deployment, a cloud
region or project). Pointing such a config elsewhere needs secrets:USE. Writes that leave
the destination where it is stay free, and so does switching the model: a model row holds
no endpoint, it only picks between vendors' own hosts.

An MCP tool sends its auth secret to its `transport`, so the same rule holds for it.

The Twilio channel's create, which updates the channel's existing row in place, is a
write path of its own and is covered here too, as is the MCP tool's PUT, which fills
fields missing from the body before it saves."""

import pytest

from rbac.models.enums import Permission, ResourceType
from ai_models.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider
from tables.models.mcp_models import McpTool
from tables.models.realtime_models import OpenAIRealtimeConfig
from tables.models.webhook_models import RealtimeChannel, TwilioChannel
from tables.services.secrets import SecretUseDeniedError, secret_service
from tables.services.secrets.secret_use_checks import check_llm_config_write
from tables.services.secrets.secret_use_service import SecretActor
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants
from tests.rbac_cross_org_fixtures import beta  # noqa: F401

GATEWAY_URL = "https://gateway.example.com/v1"
ATTACKER_URL = "https://attacker.example.com/v1"
MARKER_HEADERS = {"Authorization": "Bearer epicstaff_secret(GATEWAY_TOKEN)"}
DENIED = 'Changing where this sends its secrets requires the "Use" permission'


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
def gateway_token(default_org):
    return secret_service.create(text="gateway-token", org=default_org, name="GATEWAY_TOKEN")


def _builtin(provider_name, name, model_class=LLMModel, provider_field="llm_provider"):
    provider = Provider.objects.get_or_create(name=provider_name)[0]
    return model_class.objects.create(name=name, predefined=True, **{provider_field: provider})


@pytest.fixture
def secret_llm_config(default_org, gpt_4o_llm, secret_a):
    return LLMConfig.objects.create(
        custom_name="destination-secret-config",
        model=gpt_4o_llm,
        api_key_secret=secret_a,
        connection={"base_url": GATEWAY_URL},
        org=default_org,
    )


@pytest.fixture
def secret_embedding_config(default_org, embedding_model, secret_a):
    return EmbeddingConfig.objects.create(
        custom_name="destination-secret-embedder",
        model=embedding_model,
        api_key_secret=secret_a,
        connection={"base_url": GATEWAY_URL},
        org=default_org,
    )


def _patch_connection(client, config, connection, endpoint="/api/llm-configs/"):
    return client.patch(f"{endpoint}{config.pk}/", {"connection": connection}, format="json")


def _denied(response, field_name):
    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith(f"connection: {field_name}: {DENIED}")


@pytest.mark.django_db
def test_llm_config_base_url_change_with_api_key_denied(no_use_client, secret_llm_config):
    response = _patch_connection(no_use_client, secret_llm_config, {"base_url": ATTACKER_URL})

    _denied(response, "base_url")
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.connection == {"base_url": GATEWAY_URL}


@pytest.mark.django_db
@pytest.mark.parametrize("connection", [{}, {"base_url": ""}], ids=["removed", "emptied"])
def test_clearing_the_base_url_of_a_secret_config_is_a_change_too(
    no_use_client, secret_llm_config, connection
):
    # Without a base URL the key goes to the vendor's default host, which is still a move.
    response = _patch_connection(no_use_client, secret_llm_config, connection)

    _denied(response, "base_url")


@pytest.mark.django_db
def test_base_url_change_on_header_marker_only_config_denied(no_use_client, default_org, gpt_4o_llm):
    config = LLMConfig.objects.create(
        custom_name="destination-marker-config",
        model=gpt_4o_llm,
        extra_headers=MARKER_HEADERS,
        org=default_org,
    )

    response = _patch_connection(no_use_client, config, {"base_url": ATTACKER_URL})

    _denied(response, "base_url")
    config.refresh_from_db()
    assert config.connection == {}


@pytest.mark.django_db
def test_region_change_on_connection_marker_only_config_denied(no_use_client, default_org, gateway_token):
    # The AWS access key id is the config's only secret; the region picks the host it goes to.
    connection = {"aws_access_key_id": "epicstaff_secret(GATEWAY_TOKEN)", "aws_region_name": "eu-west-1"}
    config = LLMConfig.objects.create(
        custom_name="destination-connection-marker",
        model=_builtin("bedrock", "ai21.j2-mid-v1"),
        connection=connection,
        org=default_org,
    )

    response = _patch_connection(no_use_client, config, {**connection, "aws_region_name": "us-east-1"})

    _denied(response, "aws_region_name")
    config.refresh_from_db()
    assert config.connection == connection


@pytest.mark.django_db
def test_dropping_all_markers_while_changing_base_url_is_free(no_use_client, default_org, gpt_4o_llm):
    # Whether the config carries a secret is judged after the write: once this
    # request drops the only marker, nothing is sent to the new host.
    config = LLMConfig.objects.create(
        custom_name="destination-marker-dropped",
        model=gpt_4o_llm,
        extra_headers=MARKER_HEADERS,
        org=default_org,
    )

    response = no_use_client.patch(
        f"/api/llm-configs/{config.pk}/",
        {"extra_headers": {}, "connection": {"base_url": ATTACKER_URL}},
        format="json",
    )

    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert (config.extra_headers, config.connection) == ({}, {"base_url": ATTACKER_URL})


@pytest.mark.django_db
def test_azure_deployment_is_an_endpoint_and_the_api_version_is_not(no_use_client, default_org, secret_a):
    connection = {"base_url": GATEWAY_URL, "deployment_id": "prod", "api_version": "2024-06-01"}
    config = LLMConfig.objects.create(
        custom_name="destination-azure",
        model=_builtin("azure", "azure/gpt-4o"),
        api_key_secret=secret_a,
        connection=connection,
        org=default_org,
    )

    redeployed = _patch_connection(no_use_client, config, {**connection, "deployment_id": "other"})
    reversioned = _patch_connection(no_use_client, config, {**connection, "api_version": "2025-01-01"})

    _denied(redeployed, "deployment_id")
    assert reversioned.status_code == 200, reversioned.json()
    config.refresh_from_db()
    assert config.connection == {**connection, "api_version": "2025-01-01"}


@pytest.mark.django_db
def test_switching_the_model_of_a_secret_config_is_free(no_use_client, secret_llm_config):
    # A model row holds no endpoint, so the key keeps going to the connection's base URL.
    other_model = _builtin("openai", "gpt-4o-mini")

    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"model": other_model.pk}, format="json"
    )

    assert response.status_code == 200, response.json()
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.model_id == other_model.pk


@pytest.mark.django_db
def test_unrelated_field_edit_is_free(no_use_client, secret_llm_config):
    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/",
        {"parameters": {"temperature": 0.9}, "connection": {"base_url": GATEWAY_URL}},
        format="json",
    )

    assert response.status_code == 200, response.json()
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.parameters == {"temperature": 0.9}


@pytest.mark.django_db
@pytest.mark.parametrize("stored, sent", [({}, {"base_url": ""}), ({"base_url": ""}, {})])
def test_empty_and_missing_base_url_are_same_destination(no_use_client, secret_llm_config, stored, sent):
    LLMConfig.objects.filter(pk=secret_llm_config.pk).update(connection=stored)

    response = _patch_connection(no_use_client, secret_llm_config, sent)

    assert response.status_code == 200, response.json()
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.connection == sent


@pytest.mark.django_db
def test_base_url_change_without_secret_is_free(no_use_client, default_org, gpt_4o_llm):
    config = LLMConfig.objects.create(
        custom_name="destination-plain-config",
        model=gpt_4o_llm,
        extra_headers={"X-Trace": "plain"},
        org=default_org,
    )

    response = _patch_connection(no_use_client, config, {"base_url": ATTACKER_URL})

    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert config.connection == {"base_url": ATTACKER_URL}


@pytest.mark.django_db
def test_creating_a_secret_config_with_a_base_url_needs_only_the_secret_check(
    use_client, no_use_client, gpt_4o_llm, secret_a
):
    body = {"custom_name": "destination-new", "model": gpt_4o_llm.pk, "connection": {"base_url": ATTACKER_URL}}

    with_secret = no_use_client.post("/api/llm-configs/", {**body, "api_key_secret_id": secret_a.pk}, format="json")
    without_secret = no_use_client.post("/api/llm-configs/", body, format="json")
    with_use = use_client.post(
        "/api/llm-configs/", {**body, "custom_name": "destination-new-2", "api_key_secret_id": secret_a.pk}, format="json"
    )

    assert with_secret.status_code == 400 and with_secret.json()["message"].startswith("api_key_secret_id:")
    assert without_secret.status_code == 201, without_secret.json()
    assert with_use.status_code == 201, with_use.json()


@pytest.mark.django_db
def test_built_in_model_edit_stays_immutable_without_use(no_use_client, gpt_4o_llm):
    response = no_use_client.patch(f"/api/llm-models/{gpt_4o_llm.pk}/", {"name": "renamed"}, format="json")

    assert response.status_code == 403, response.json()
    gpt_4o_llm.refresh_from_db()
    assert gpt_4o_llm.name == "gpt-4o"


@pytest.mark.django_db
def test_embedding_config_base_url_change_denied(no_use_client, secret_embedding_config):
    response = _patch_connection(
        no_use_client, secret_embedding_config, {"base_url": ATTACKER_URL}, endpoint="/api/embedding-configs/"
    )

    _denied(response, "base_url")
    secret_embedding_config.refresh_from_db()
    assert secret_embedding_config.connection == {"base_url": GATEWAY_URL}


@pytest.mark.django_db
def test_embedding_config_model_switch_is_free(no_use_client, secret_embedding_config):
    other_model = _builtin("openai", "text-embedding-3-large", EmbeddingModel, "embedding_provider")

    response = no_use_client.patch(
        f"/api/embedding-configs/{secret_embedding_config.pk}/", {"model": other_model.pk}, format="json"
    )

    assert response.status_code == 200, response.json()
    secret_embedding_config.refresh_from_db()
    assert secret_embedding_config.model_id == other_model.pk


@pytest.mark.django_db
def test_holder_of_use_may_change_destination(use_client, secret_llm_config, secret_embedding_config):
    config_response = _patch_connection(use_client, secret_llm_config, {"base_url": ATTACKER_URL})
    embedder_response = _patch_connection(
        use_client, secret_embedding_config, {"base_url": ATTACKER_URL}, endpoint="/api/embedding-configs/"
    )

    assert config_response.status_code == 200, config_response.json()
    assert embedder_response.status_code == 200, embedder_response.json()
    secret_llm_config.refresh_from_db()
    secret_embedding_config.refresh_from_db()
    assert secret_llm_config.connection == {"base_url": ATTACKER_URL}
    assert secret_embedding_config.connection == {"base_url": ATTACKER_URL}


@pytest.mark.django_db
def test_a_connection_key_no_provider_declares_counts_as_an_endpoint(default_org, secret_a, django_user_model):
    # A provider the catalog no longer knows declares no fields, so nothing tells which
    # key moves the requests: every key is treated as one.
    provider = Provider.objects.create(name="provider-the-catalog-dropped")
    config = LLMConfig.objects.create(
        custom_name="destination-unknown-provider",
        model=LLMModel.objects.create(name="old-model", llm_provider=provider, predefined=True),
        api_key_secret=secret_a,
        connection={"api_host": GATEWAY_URL},
        org=default_org,
    )
    user = django_user_model.objects.create_user(email="destination-member@example.com", password="x")

    with pytest.raises(SecretUseDeniedError) as denial:
        check_llm_config_write(
            SecretActor(user=user, org_id=default_org.pk), config, {"connection": {"api_host": ATTACKER_URL}}
        )

    assert denial.value.field_path == ("connection", "api_host")


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
