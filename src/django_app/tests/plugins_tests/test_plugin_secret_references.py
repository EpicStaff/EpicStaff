"""A plugin's service account may reference only the secrets it created itself.

A row that references a secret also says where its value goes (an LLM config's `base_url`,
an MCP tool's URL, a Python tool's code). If a plugin could reference any of the
organization's secrets, it could aim one at a server of its own and read the value.
"""

from contextlib import contextmanager

import pytest
from django.db import connection
from django.contrib.contenttypes.models import ContentType
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from plugins.models import PluginGrant, PluginOwnedResource
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory
from django.urls import reverse
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.graph_versioning.services import GraphVersioningService
from tables.models import EmbeddingConfig, Graph, LLMConfig, Secret
from tables.models.graph_models import PythonNode, StartNode, TelegramTriggerNode
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.webhook_models import WebhookTrigger, WebhookTriggerAuth, WebhookTriggerAuthKind
from tables.services.secrets import SecretUseDeniedError, secret_service, secret_use_checks
from tables.services.secrets.request_actor import actor_from_request
from tables.services.secrets.secret_use_service import secret_use_service

from tests.helpers import UNRESTRICTED_EXPORT_POLICY, data_to_json_file
from tests.plugins_tests.conftest import GATEWAY_SECRET, service_account_client
from tests.services_tests.test_secret_reference_coverage import SECRET_USE_CHECK_BY_SERIALIZER

pytestmark = [pytest.mark.django_db]

ORG_SECRET_NAME = "ACME_PROVIDER_KEY"
REFUSED = "This credential can reference only secrets it created"
ACCESS = [
    {"resource_type": "secrets", "actions": ["read", "create", "use"], "reason": "Stores its own keys."},
    {"resource_type": "llm_configs", "actions": ["read", "create", "update"], "reason": "Its LLM configs."},
    {"resource_type": "tools", "actions": ["read", "create", "update"], "reason": "Its tools."},
    {"resource_type": "flows", "actions": ["read", "create", "update", "use"], "reason": "Its flows."},
    {"resource_type": "webhooks", "actions": ["read", "create", "update"], "reason": "Its bots."},
]
# The guarded (serializer, field) pairs found today; a floor, so the walk below can never
# lose serializers silently.
MINIMUM_GUARDED_FIELDS = 18
# The same floor for header fields whose `epicstaff_secret(<name>)` markers name secrets.
MINIMUM_GUARDED_MARKER_FIELDS = 2


@pytest.fixture
def plugin(weather_backend):
    return weather_backend(access=ACCESS)


@pytest.fixture
def acme_key(plugin, service_account_key, acme):
    return service_account_key(plugin, acme)


@pytest.fixture
def client(acme_key, acme):
    return service_account_client(acme_key, acme)


@pytest.fixture
def org_secret(acme):
    return secret_service.create(text="sk-acme-real-key", org=acme, name=ORG_SECRET_NAME)


@pytest.fixture
def own_secret(client):
    response = client.post("/api/secrets/", {"name": "Weather key", "value": "sk-weather"}, format="json")
    assert response.status_code == 201, response.content
    return Secret.objects.get(pk=response.json()["id"])


def _refused(response, field):
    assert response.status_code == 400, response.content
    message = response.json()["message"]
    assert field in message and REFUSED in message
    assert ORG_SECRET_NAME not in response.content.decode()


# ---- the plugin's own secrets ----


def test_a_plugin_references_a_secret_it_created(client, own_secret):
    created = client.post(
        "/api/llm-configs/", {"custom_name": "Weather summaries", "api_key_secret_id": own_secret.pk}, format="json"
    )
    assert created.status_code == 201, created.content

    updated = client.patch(f"/api/llm-configs/{created.json()['id']}/", {"base_url": "https://llm.example.com"}, format="json")

    assert updated.status_code == 200, updated.content
    assert LLMConfig.objects.get(pk=created.json()["id"]).api_key_secret == own_secret


def test_a_config_linked_to_its_own_binned_secret_can_still_be_edited(client, own_secret):
    config_id = client.post(
        "/api/llm-configs/", {"custom_name": "Binned key", "api_key_secret_id": own_secret.pk}, format="json"
    ).json()["id"]
    own_secret.delete()

    response = client.patch(f"/api/llm-configs/{config_id}/", {"temperature": 0.2}, format="json")

    assert response.status_code == 200, response.content


def test_a_secret_owned_under_no_grant_of_this_plugin_is_refused(client, acme):
    secret = secret_service.create(text="sk-orphan", org=acme, name=ORG_SECRET_NAME)
    PluginOwnedResource.objects.create(
        org=acme,
        grant=None,
        plugin_identifier="weather",
        content_type=ContentType.objects.get_for_model(Secret),
        object_id=secret.pk,
    )

    response = client.post("/api/llm-configs/", {"custom_name": "Orphan", "api_key_secret_id": secret.pk}, format="json")

    _refused(response, "api_key_secret_id")


# ---- the organization's secrets ----


def test_referencing_an_org_secret_on_create_is_refused(client, org_secret):
    response = client.post(
        "/api/llm-configs/",
        {"custom_name": "Exfiltrate", "base_url": "https://attacker.example", "api_key_secret_id": org_secret.pk},
        format="json",
    )

    _refused(response, "api_key_secret_id")
    assert not LLMConfig.objects.filter(custom_name="Exfiltrate").exists()


@pytest.fixture
def org_llm_config(acme, org_secret):
    return LLMConfig.objects.create(custom_name="Acme production", org=acme, api_key_secret=org_secret)


def test_changing_only_the_base_url_of_an_org_config_with_an_org_secret_is_refused(client, org_llm_config):
    response = client.patch(f"/api/llm-configs/{org_llm_config.pk}/", {"base_url": "https://attacker.example"}, format="json")

    _refused(response, "api_key_secret_id")
    org_llm_config.refresh_from_db()
    assert org_llm_config.base_url is None


def test_resending_the_org_secret_unchanged_is_refused_too(client, org_llm_config, org_secret):
    response = client.put(
        f"/api/llm-configs/{org_llm_config.pk}/",
        {"custom_name": "Acme production", "base_url": "https://attacker.example", "api_key_secret_id": org_secret.pk},
        format="json",
    )

    _refused(response, "api_key_secret_id")


def test_an_embedding_config_with_an_org_secret_cannot_be_changed(client, acme, org_secret):
    config = EmbeddingConfig.objects.create(custom_name="Acme embeddings", org=acme, api_key_secret=org_secret)

    response = client.patch(f"/api/embedding-configs/{config.pk}/", {"custom_name": "Renamed"}, format="json")

    _refused(response, "api_key_secret_id")


def test_an_mcp_tool_cannot_send_an_org_secret(client, acme, org_secret):
    created = client.post(
        "/api/mcp-tools/",
        {"name": "Exfiltrate", "transport": "https://attacker.example/mcp", "tool_name": "x", "auth_secret_id": org_secret.pk},
        format="json",
    )
    tool = McpTool.objects.create(
        name="Acme search", transport="https://mcp.acme.example", tool_name="search", auth_secret=org_secret, org=acme
    )
    redirected = client.patch(f"/api/mcp-tools/{tool.pk}/", {"transport": "https://attacker.example/mcp"}, format="json")

    _refused(created, "auth_secret_id")
    _refused(redirected, "auth_secret_id")
    tool.refresh_from_db()
    assert tool.transport == "https://mcp.acme.example"


def test_python_code_cannot_read_an_org_secret(client, acme, org_secret):
    created = client.post(
        "/api/python-code-tool/",
        {
            "name": "Exfiltrate",
            "description": "d",
            "python_code": {"code": "def main(): return 1", "entrypoint": "main", "libraries": [], "secret_ids": [org_secret.pk]},
        },
        format="json",
    )
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    python_code.secrets.add(org_secret)
    tool = PythonCodeTool.objects.create(name="Acme tool", description="d", python_code=python_code, org=acme)
    rewritten = client.patch(
        f"/api/python-code-tool/{tool.pk}/",
        {"python_code": {"code": "def main(): return 2", "entrypoint": "main", "libraries": []}},
        format="json",
    )

    _refused(created, "secret_ids")
    _refused(rewritten, "secret_ids")
    python_code.refresh_from_db()
    assert python_code.code == "def main(): return 1"


def test_dropping_the_org_secret_is_not_a_reference(client, org_llm_config):
    response = client.patch(f"/api/llm-configs/{org_llm_config.pk}/", {"api_key_secret_id": None}, format="json")

    assert response.status_code == 200, response.content


# ---- a secret marker in a config's headers names a secret too ----

CONFIG_ENDPOINTS = [("/api/llm-configs/", LLMConfig), ("/api/embedding-configs/", EmbeddingConfig)]


def _marker_headers(secret_name):
    return {"Authorization": f"Bearer epicstaff_secret({secret_name})", "X-Trace": "plain"}


@pytest.mark.parametrize("endpoint, model", CONFIG_ENDPOINTS)
def test_a_header_marker_of_an_org_secret_is_refused(client, org_secret, endpoint, model):
    response = client.post(
        endpoint, {"custom_name": "Exfiltrate", "extra_headers": _marker_headers(ORG_SECRET_NAME)}, format="json"
    )

    _refused(response, "extra_headers")
    assert not model.objects.filter(custom_name="Exfiltrate").exists()


@pytest.mark.parametrize("endpoint, model", CONFIG_ENDPOINTS)
def test_a_header_marker_of_its_own_secret_is_taken_and_kept_on_edit(client, own_secret, endpoint, model):
    created = client.post(
        endpoint, {"custom_name": "Weather", "extra_headers": _marker_headers(own_secret.name)}, format="json"
    )
    assert created.status_code == 201, created.content

    renamed = client.patch(f"{endpoint}{created.json()['id']}/", {"custom_name": "Weather renamed"}, format="json")

    assert renamed.status_code == 200, renamed.content
    assert model.objects.get(pk=created.json()["id"]).extra_headers == _marker_headers(own_secret.name)


def test_a_header_marker_naming_no_secret_is_refused(client):
    # A person could create a secret of that name later, and the config would send it.
    response = client.post(
        "/api/llm-configs/", {"custom_name": "Waiting", "extra_headers": _marker_headers("NOT_CREATED_YET")}, format="json"
    )

    _refused(response, "extra_headers")


def test_an_org_config_whose_headers_name_an_org_secret_cannot_be_changed(client, acme, org_secret):
    config = EmbeddingConfig.objects.create(
        custom_name="Acme embeddings", org=acme, extra_headers=_marker_headers(ORG_SECRET_NAME)
    )

    response = client.patch(f"/api/embedding-configs/{config.pk}/", {"custom_name": "Renamed"}, format="json")

    _refused(response, "extra_headers")
    config.refresh_from_db()
    assert config.custom_name == "Acme embeddings"


def test_dropping_an_org_secret_s_marker_is_not_a_reference(client, acme, org_secret):
    config = LLMConfig.objects.create(custom_name="Acme marked", org=acme, extra_headers=_marker_headers(ORG_SECRET_NAME))

    response = client.patch(f"/api/llm-configs/{config.pk}/", {"extra_headers": {"X-Trace": "plain"}}, format="json")

    assert response.status_code == 200, response.content


def test_a_marker_of_its_own_binned_secret_still_lets_it_edit_the_config(client, own_secret):
    config_id = client.post(
        "/api/llm-configs/", {"custom_name": "Binned marker", "extra_headers": _marker_headers(own_secret.name)}, format="json"
    ).json()["id"]
    own_secret.delete()

    response = client.patch(f"/api/llm-configs/{config_id}/", {"temperature": 0.2}, format="json")

    assert response.status_code == 200, response.content


def test_a_marker_whose_name_a_binned_org_secret_shares_is_refused(client, acme):
    # Once the plugin's secret of that name is binned, restoring the organization's one
    # would make the marker send it.
    secret_service.create(text="sk-acme-old", org=acme, name="Shared name").delete()
    created = client.post("/api/secrets/", {"name": "Shared name", "value": "sk-weather"}, format="json")
    assert created.status_code == 201, created.content

    response = client.post(
        "/api/llm-configs/", {"custom_name": "Shared", "extra_headers": _marker_headers("Shared name")}, format="json"
    )

    _refused(response, "extra_headers")


@pytest.mark.parametrize(
    "config_type, model_type, model_fixture",
    [
        (EntityType.LLM_CONFIG, EntityType.LLM_MODEL, "gpt_4o_llm"),
        (EntityType.EMBEDDING_CONFIG, EntityType.EMBEDDING_MODEL, "embedding_model"),
    ],
)
def test_a_plugin_s_config_import_takes_a_marker_of_its_own_secret_only(
    request, acme_key, acme, org_secret, own_secret, config_type, model_type, model_fixture
):
    principal = _plugin_request(acme_key, acme).user
    model = request.getfixturevalue(model_fixture)
    strategy = entity_registry.get_strategy(config_type)
    source = strategy.config_model.objects.create(custom_name="Exported", model=model, org=acme)
    exported = ExportService(entity_registry).export_entities(
        config_type, [source.pk], policy=UNRESTRICTED_EXPORT_POLICY
    ).data[config_type][0]
    id_mapper = IDMapper()
    id_mapper.map(model_type, model.pk, model.pk, was_created=False)

    def import_with_marker_of(secret_name):
        data = {**exported, "custom_name": f"Imported {secret_name}", "extra_headers": _marker_headers(secret_name)}
        return strategy.create_entity(data, id_mapper, user=principal, org_id=acme.pk)

    with pytest.raises(ValidationError) as refused:
        import_with_marker_of(ORG_SECRET_NAME)
    imported = import_with_marker_of(own_secret.name)

    assert REFUSED in str(refused.value.detail["extra_headers"])
    assert ORG_SECRET_NAME not in str(refused.value.detail)
    assert not strategy.config_model.objects.filter(custom_name=f"Imported {ORG_SECRET_NAME}").exists()
    assert imported.extra_headers == _marker_headers(own_secret.name)


# ---- every secret Use check ----


def _python_code(secret):
    return {"secrets": [secret]}


# Every secret reference a write can make, as (check, data the write carries, field reported).
# Each write is a create (no persisted row), so the reference is the one in the data.
GUARDED_REFERENCES = [
    (secret_use_checks.check_llm_config_write, lambda secret: {"api_key_secret": secret}, "api_key_secret_id"),
    (secret_use_checks.check_embedding_config_write, lambda secret: {"api_key_secret": secret}, "api_key_secret_id"),
    (secret_use_checks.check_realtime_config_write, lambda secret: {"api_key_secret": secret}, "api_key_secret_id"),
    (
        secret_use_checks.check_realtime_transcription_config_write,
        lambda secret: {"api_key_secret": secret},
        "api_key_secret_id",
    ),
    (secret_use_checks.check_openai_realtime_config_write, lambda secret: {"api_key_secret": secret}, "api_key_secret_id"),
    (
        secret_use_checks.check_openai_realtime_config_write,
        lambda secret: {"transcription_api_key_secret": secret},
        "transcription_api_key_secret_id",
    ),
    (secret_use_checks.check_elevenlabs_realtime_config_write, lambda secret: {"api_key_secret": secret}, "api_key_secret_id"),
    (secret_use_checks.check_gemini_realtime_config_write, lambda secret: {"api_key_secret": secret}, "api_key_secret_id"),
    (secret_use_checks.check_twilio_channel_write, lambda secret: {"auth_token_secret": secret}, "auth_token_secret_id"),
    (secret_use_checks.check_mcp_tool_write, lambda secret: {"auth_secret": secret}, "auth_secret_id"),
    (secret_use_checks.check_webhook_trigger_write, lambda secret: {"auth_secret_id": secret}, "auth_secret_id"),
    (
        secret_use_checks.check_webhook_trigger_write,
        lambda secret: {"ngrok_config": {"auth_token_secret": secret}},
        "auth_token_secret_id",
    ),
    (
        secret_use_checks.check_telegram_trigger_node_write,
        lambda secret: {"telegram_bot_api_key_secret": secret},
        "telegram_bot_api_key_secret_id",
    ),
    (secret_use_checks.check_python_node_write, lambda secret: {"python_code": _python_code(secret)}, "secret_ids"),
    (secret_use_checks.check_webhook_trigger_node_write, lambda secret: {"python_code": _python_code(secret)}, "secret_ids"),
    (secret_use_checks.check_python_code_tool_write, lambda secret: {"python_code": _python_code(secret)}, "secret_ids"),
    (secret_use_checks.check_cdt_node_write, lambda secret: {"pre_python_code": _python_code(secret)}, "secret_ids"),
    (secret_use_checks.check_cdt_node_write, lambda secret: {"post_python_code": _python_code(secret)}, "secret_ids"),
    (
        lambda actor, instance, data: secret_use_checks.check_quickstart(actor, data),
        lambda secret: {"api_key_secret_id": secret},
        "api_key_secret_id",
    ),
]
# The checks whose header fields carry `epicstaff_secret(<name>)` markers.
GUARDED_MARKER_CHECKS = [secret_use_checks.check_llm_config_write, secret_use_checks.check_embedding_config_write]
# The guarded (check, field) pairs found today; a floor, so the table can never lose entries
# silently.
MINIMUM_GUARDED_FIELDS = 18
# The same floor for header fields whose `epicstaff_secret(<name>)` markers name secrets.
MINIMUM_GUARDED_MARKER_FIELDS = 2


def _plugin_request(acme_key, acme):
    request = Request(
        APIRequestFactory().post(
            "/",
            HTTP_AUTHORIZATION=f"PluginKey {acme_key}",
            HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET,
            HTTP_X_ORGANIZATION_ID=str(acme.pk),
        ),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    assert request.user.is_plugin_credential
    return request


def _plugin_actor(acme_key, acme):
    return actor_from_request(_plugin_request(acme_key, acme))


def test_the_table_covers_every_secret_use_check():
    # check_python_code_write is reached through each Python-code parent's own check.
    mapped = set(SECRET_USE_CHECK_BY_SERIALIZER.values()) - {"check_python_code_write"}
    tabled = {check.__name__ for check, _, _ in GUARDED_REFERENCES} | {"check_quickstart"}

    assert mapped <= tabled, mapped - tabled


def test_every_guarded_field_refuses_an_org_secret_and_takes_the_plugin_s_own(acme_key, acme, org_secret, own_secret):
    actor = _plugin_actor(acme_key, acme)
    checked, failures = [], []
    for check, data_with, field_name in GUARDED_REFERENCES:
        checked.append(f"{check.__name__}.{field_name}")
        try:
            check(actor, None, data_with(own_secret))
        except SecretUseDeniedError as error:
            failures.append(f"{checked[-1]} refused the plugin's own secret: {error.field_errors()}")
        with pytest.raises(SecretUseDeniedError) as refused:
            check(actor, None, data_with(org_secret))
        if (
            refused.value.field_path[-1] != field_name
            or REFUSED not in refused.value.message
            or ORG_SECRET_NAME in str(refused.value.field_errors())
        ):
            failures.append(f"{checked[-1]} answered {refused.value.field_errors()}")

    assert failures == []
    assert len(checked) >= MINIMUM_GUARDED_FIELDS, checked


def test_every_guarded_header_field_refuses_an_org_secret_s_marker_and_takes_the_plugin_s_own(
    acme_key, acme, org_secret, own_secret
):
    actor = _plugin_actor(acme_key, acme)
    checked, failures = [], []
    for check in GUARDED_MARKER_CHECKS:
        checked.append(f"{check.__name__}.extra_headers")

        def write(secret_name):
            check(actor, None, {"extra_headers": _marker_headers(secret_name)})

        try:
            write(own_secret.name)
        except SecretUseDeniedError as error:
            failures.append(f"{checked[-1]} refused the plugin's own secret: {error.field_errors()}")
        with pytest.raises(SecretUseDeniedError) as refused:
            write(ORG_SECRET_NAME)
        if (
            refused.value.field_path != ("extra_headers",)
            or REFUSED not in refused.value.message
            or ORG_SECRET_NAME in str(refused.value.field_errors())
        ):
            failures.append(f"{checked[-1]} answered {refused.value.field_errors()}")

    assert failures == []
    assert len(checked) >= MINIMUM_GUARDED_MARKER_FIELDS, checked


# ---- everyone else ----


def test_a_person_with_the_same_rights_still_references_org_secrets(acme, org_secret, org_llm_config, django_user_model):
    role = Role.objects.create(name="Config editor", org=acme, is_built_in=False)
    RolePermission.objects.create(role=role, resource_type=ResourceType.SECRETS.value, permissions=int(Permission.READ | Permission.CREATE | Permission.USE))
    RolePermission.objects.create(role=role, resource_type=ResourceType.LLM_CONFIGS.value, permissions=int(Permission.READ | Permission.CREATE | Permission.UPDATE))
    person = django_user_model.objects.create_user(email="config-editor@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=person, org=acme, role=role)
    client = APIClient()
    client.force_authenticate(user=person)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    created = client.post("/api/llm-configs/", {"custom_name": "Person's", "api_key_secret_id": org_secret.pk}, format="json")
    updated = client.patch(f"/api/llm-configs/{org_llm_config.pk}/", {"base_url": "https://llm.acme.example"}, format="json")

    assert (created.status_code, updated.status_code) == (201, 200), (created.content, updated.content)


def test_a_plugin_in_another_organization_gets_not_found(plugin, service_account_key, acme, beta, org_llm_config):
    beta_client = service_account_client(service_account_key(plugin, beta), beta)

    response = beta_client.patch(f"/api/llm-configs/{org_llm_config.pk}/", {"base_url": "https://attacker.example"}, format="json")

    assert response.status_code == 404
    assert PluginGrant.objects.filter(org=beta).exists()


# ---- a bulk save of a flow ----

NEUTRAL_CODE = "def main(**kwargs):\n    return 1\n"


def _python_node(graph, secret, name):
    python_code = PythonCode.objects.create(code=NEUTRAL_CODE, entrypoint="main")
    python_code.secrets.add(secret)
    return PythonNode.objects.create(graph=graph, node_name=name, python_code=python_code)


def _bulk_save(client, graph, nodes, *, code=NEUTRAL_CODE, secret_ids=None):
    def python_code(node):
        body = {"code": code, "entrypoint": "main", "libraries": [], "global_kwargs": {}}
        if secret_ids is not None:
            body["secret_ids"] = secret_ids
        return body

    graph.refresh_from_db()
    return client.post(
        f"/api/graphs/{graph.pk}/save/",
        {
            "save_version": graph.save_version,
            "python_node_list": [
                {"id": node.pk, "graph": graph.pk, "node_name": node.node_name, "python_code": python_code(node)}
                for node in nodes
            ],
        },
        format="json",
    )


def test_a_bulk_save_of_an_org_flow_whose_node_uses_an_org_secret_is_refused(client, acme, org_secret):
    graph = Graph.objects.create(name="Acme flow", org=acme)
    node = _python_node(graph, org_secret, "uses_the_org_key")

    response = _bulk_save(client, graph, [node], code="def main(**kwargs):\n    return 2\n")

    assert response.status_code == 400, response.content
    [message] = response.json()["errors"]["python_node_list"][0]["errors"]["python_code"]["secret_ids"]
    assert REFUSED in message
    assert ORG_SECRET_NAME not in response.content.decode()
    node.python_code.refresh_from_db()
    assert node.python_code.code == NEUTRAL_CODE


def test_reading_a_stored_reference_the_payload_leaves_out_costs_no_query(acme_key, acme, own_secret, django_assert_num_queries):
    config = LLMConfig.objects.get(pk=LLMConfig.objects.create(custom_name="Weather summaries", org=acme, api_key_secret=own_secret).pk)
    actor = _plugin_actor(acme_key, acme)
    # The plugin's own secrets are confirmed once per principal; confirm it before counting.
    secret_use_checks.check_llm_config_write(actor, config, {"api_key_secret": own_secret})

    with django_assert_num_queries(0):
        secret_use_checks.check_llm_config_write(actor, config, {})


def test_a_bulk_save_of_many_nodes_resolves_secrets_use_once(client, own_secret, mocker):
    graph = Graph.objects.get(pk=client.post("/api/graphs/", {"name": "Weather flow"}, format="json").json()["id"])
    # Declared by none of them yet: adding the secret to each node needs secrets:USE.
    nodes = [
        PythonNode.objects.create(
            graph=graph, node_name=f"node_{index}", python_code=PythonCode.objects.create(code=NEUTRAL_CODE, entrypoint="main")
        )
        for index in range(3)
    ]
    use_resolutions = mocker.spy(secret_use_service._resolver, "resolve")

    response = _bulk_save(client, graph, nodes, secret_ids=[own_secret.pk])

    assert response.status_code == 200, response.content
    assert use_resolutions.call_count == 1


@contextmanager
def _statements_inside_the_stored_reference_lookup(monkeypatch):
    """The SQL run inside `linked_ids`, the secret Use check's read of a node's stored references."""
    statements, depth = [], [0]
    lookup = secret_use_checks.linked_ids

    def counted_lookup(value):
        depth[0] += 1
        try:
            return lookup(value)
        finally:
            depth[0] -= 1

    def record(execute, sql, params, many, context):
        if depth[0]:
            statements.append(sql)
        return execute(sql, params, many, context)

    monkeypatch.setattr(secret_use_checks, "linked_ids", counted_lookup)
    with connection.execute_wrapper(record):
        yield statements


def test_the_stored_reference_lookups_cost_the_same_for_10_or_30_nodes_a_plugin_saves(client, own_secret, monkeypatch):
    def guard_statements(count):
        graph = Graph.objects.get(pk=client.post("/api/graphs/", {"name": f"Flow of {count}"}, format="json").json()["id"])
        nodes = [_python_node(graph, own_secret, f"node_{index}") for index in range(count)]
        with _statements_inside_the_stored_reference_lookup(monkeypatch) as statements:
            response = _bulk_save(client, graph, nodes)
        assert response.status_code == 200, response.content
        return len(statements)

    assert guard_statements(10) == guard_statements(30) == 0


@pytest.mark.parametrize("stored", ["own_secret", "org_secret"])
def test_a_stored_foreign_key_is_compared_by_its_id_without_loading_the_secret(
    request, acme_key, acme, own_secret, org_secret, stored, django_assert_num_queries
):
    config_id = LLMConfig.objects.create(custom_name="By id", org=acme, api_key_secret=request.getfixturevalue(stored)).pk
    config = LLMConfig.objects.get(pk=config_id)
    actor = _plugin_actor(acme_key, acme)
    # The plugin's own secrets are confirmed once per principal; confirm it before counting.
    actor.principal.may_reference_secrets(frozenset({own_secret.pk}))

    if stored == "own_secret":
        with django_assert_num_queries(0):
            secret_use_checks.check_llm_config_write(actor, config, {})
    else:
        with pytest.raises(SecretUseDeniedError) as refused:
            secret_use_checks.check_llm_config_write(actor, config, {})
        assert refused.value.field_path == ("api_key_secret_id",)


def test_a_webhook_trigger_s_stored_secret_costs_only_its_auth_row(acme_key, acme, own_secret, django_assert_num_queries):
    trigger = WebhookTrigger.objects.create(path="by-id", org=acme)
    WebhookTriggerAuth.objects.create(trigger=trigger, kind=WebhookTriggerAuthKind.WEBHOOK, secret=own_secret)
    actor = _plugin_actor(acme_key, acme)
    actor.principal.may_reference_secrets(frozenset({own_secret.pk}))
    instance = WebhookTrigger.objects.get(pk=trigger.pk)

    with django_assert_num_queries(1):
        secret_use_checks.check_webhook_trigger_write(actor, instance, {})


# ---- a replace-import never re-links an organization's bot key ----


def _flow_with_a_telegram_bot(organization, bot_key, path):
    graph = Graph.objects.create(name=f"Bot flow {path}", org=organization, metadata={"nodes": [], "edges": []})
    StartNode.objects.create(graph=graph, variables={})
    trigger = WebhookTrigger.objects.create(path=path, org=organization)
    WebhookTriggerAuth.objects.create(trigger=trigger, kind=WebhookTriggerAuthKind.TELEGRAM)
    TelegramTriggerNode.objects.create(graph=graph, node_name="Telegram Bot #1", webhook_trigger=trigger, telegram_bot_api_key_secret=bot_key)
    return graph


def _replace_import(client, graph):
    export_data = ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [graph.pk], policy=UNRESTRICTED_EXPORT_POLICY
    ).data
    return client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json"), "preserve_uuids": True, "replace_existing": True},
        format="multipart",
    )


def test_a_plugin_s_replace_import_drops_the_org_s_bot_key(client, acme, org_secret, mock_telegram_service, log_messages):
    graph = _flow_with_a_telegram_bot(acme, org_secret, "acme-bot")

    response = _replace_import(client, graph)

    assert response.status_code == 200, response.content
    assert graph.telegram_trigger_node_list.get().telegram_bot_api_key_secret_id is None
    trigger_id = WebhookTrigger.objects.get(path="acme-bot").pk
    assert [
        line
        for line in log_messages
        if line.startswith(f"Graph {graph.pk}: the bot key of the Telegram trigger node on webhook trigger {trigger_id}")
        and "may not use it" in line
    ]


def test_a_plugin_s_replace_import_keeps_its_own_bot_key(client, acme, own_secret, mock_telegram_service):
    graph = _flow_with_a_telegram_bot(acme, own_secret, "weather-bot")

    response = _replace_import(client, graph)

    assert response.status_code == 200, response.content
    assert graph.telegram_trigger_node_list.get().telegram_bot_api_key_secret_id == own_secret.pk


# ---- a version restore never binds a plugin's node to a secret it didn't create ----

_READS_SECRET = 'def main(**kwargs):\n    return get_secret("{name}")\n'


def _flow_with_a_declaring_node(organization, secret):
    graph = Graph.objects.create(name="Declaring flow", org=organization, metadata={"nodes": [], "edges": []})
    StartNode.objects.create(graph=graph, variables={})
    python_code = PythonCode.objects.create(code=_READS_SECRET.format(name=secret.name), entrypoint="main")
    python_code.secrets.add(secret)
    PythonNode.objects.create(graph=graph, node_name="reader", python_code=python_code)
    return graph


def test_create_graph_from_version_does_not_bind_a_plugin_to_an_org_secret(acme_key, acme, org_secret, log_messages):
    # A person's flow declares the organization's secret; a plugin builds a new flow from a
    # version of it. The new node is the plugin's, so it must not be bound to that secret.
    source = _flow_with_a_declaring_node(acme, org_secret)
    version = GraphVersioningService().save_version(graph=source, name="v1")

    result = GraphVersioningService().create_graph_from_version(version, user=_plugin_request(acme_key, acme).user)

    new_graph = Graph.objects.get(pk=result["graph_id"])
    reader = new_graph.python_node_list.get()
    assert list(reader.python_code.secrets.all()) == []
    assert any(warning["type"] == "secret_declaration_dropped" for warning in result["warnings"])
    assert any("may not use it" in line for line in log_messages)


def test_create_graph_from_version_keeps_a_secret_the_plugin_created(acme_key, acme, own_secret):
    source = _flow_with_a_declaring_node(acme, own_secret)
    version = GraphVersioningService().save_version(graph=source, name="v1")

    result = GraphVersioningService().create_graph_from_version(version, user=_plugin_request(acme_key, acme).user)

    reader = Graph.objects.get(pk=result["graph_id"]).python_node_list.get()
    assert list(reader.python_code.secrets.values_list("pk", flat=True)) == [own_secret.pk]


def test_a_person_restoring_a_version_still_rebinds_the_org_secret(acme, org_secret, admin_acme):
    source = _flow_with_a_declaring_node(acme, org_secret)
    version = GraphVersioningService().save_version(graph=source, name="v1")

    GraphVersioningService().create_graph_from_version(version, user=admin_acme)

    reader = Graph.objects.filter(org=acme).exclude(pk=source.pk).get().python_node_list.get()
    assert list(reader.python_code.secrets.values_list("pk", flat=True)) == [org_secret.pk]
