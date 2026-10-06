import json

import pytest

from plugins.samples.zip_builder import build_sample_zip, sample_files
from plugins.services.install_service import PluginInstallService
from plugins.services.secret_destinations import endpoint_host
from tables.models import EmbeddingModel, LLMConfig, Secret
from tables.services.secrets.secret_service import secret_service
from tests.plugins_tests.helpers import INSPECT_URL, PLUGINS_URL, SECRETS, plugin_url, registered_ids, upload

DEFAULT_LLM = {"resource_type": "llm_config", "name": "Chat Bot GPT-4o mini", "provider": "openai", "host": None}
DEFAULT_EMBEDDINGS = {
    "resource_type": "embedding_config",
    "name": "Chat Bot embeddings",
    "provider": "openai",
    "host": None,
}


def _resources_bytes(change) -> bytes:
    """The sample's resources.json after `change(resources)` altered it in place."""
    resources = json.loads(sample_files()["resources.json"])
    change(resources)
    return json.dumps(resources).encode()


def _sample_with_resources(change) -> bytes:
    return build_sample_zip(replace={"resources.json": _resources_bytes(change)})


def _set_embedding_model_base_url(url: str):
    def change(resources):
        resources["EmbeddingModel"][0]["base_url"] = url

    return change


def _inspect_slot(admin_client, content: bytes) -> dict:
    response = admin_client.post(INSPECT_URL, {"file": upload(content)}, format="multipart")
    assert response.status_code == 200, response.content
    [slot] = response.json()["secret_slots"]
    return slot


# --- endpoint_host ------------------------------------------------------------------


@pytest.mark.parametrize(
    "urls, expected",
    [
        ((None,), None),
        (("",), None),
        (("   ",), None),
        (("https://Api.Example.com:8443/v1",), "api.example.com"),
        (("embeddings.example.com/v1",), "embeddings.example.com"),
        (("localhost:11434",), "localhost"),
        (("http://user:secret@collector.example/x",), "collector.example"),
        (("http://[::1]:8080/",), "::1"),
        # Unreadable, but not blank: shown as written, never as the standard endpoint.
        (("http://[broken",), "http://[broken"),
        ((None, "https://second.example/v1"), "second.example"),
        (("https://first.example", "https://second.example"), "first.example"),
    ],
)
def test_endpoint_host(urls, expected):
    assert endpoint_host(*urls) == expected


# --- install review (inspect) -------------------------------------------------------


@pytest.mark.django_db
def test_inspect_lists_every_resource_a_slot_is_sent_to_with_null_host_for_the_standard_endpoint(
    admin_client, sample_zip
):
    slot = _inspect_slot(admin_client, sample_zip)

    assert slot["name"] == "OPENAI_API_KEY"
    assert slot["destinations"] == [DEFAULT_LLM, DEFAULT_EMBEDDINGS]


@pytest.mark.django_db
def test_inspect_shows_the_host_of_a_custom_model_base_url(admin_client):
    content = _sample_with_resources(_set_embedding_model_base_url("https://Embeddings.Example.com/v1"))

    slot = _inspect_slot(admin_client, content)

    assert slot["destinations"] == [
        DEFAULT_LLM,
        {**DEFAULT_EMBEDDINGS, "host": "embeddings.example.com"},
    ]


@pytest.mark.django_db
def test_inspect_shows_the_host_of_an_llm_configs_own_base_url(admin_client):
    def change(resources):
        resources["LLMConfig"][0]["base_url"] = "https://collector.example/v1"

    slot = _inspect_slot(admin_client, _sample_with_resources(change))

    assert slot["destinations"][0] == {**DEFAULT_LLM, "host": "collector.example"}


@pytest.mark.django_db
def test_inspect_prefers_the_model_base_url_the_runtime_sends_to(admin_client):
    def change(resources):
        resources["LLMModel"][0]["base_url"] = "https://model.example/v1"
        resources["LLMConfig"][0]["base_url"] = "https://config.example/v1"

    slot = _inspect_slot(admin_client, _sample_with_resources(change))

    assert slot["destinations"][0]["host"] == "model.example"


@pytest.mark.django_db
def test_inspect_lists_an_mcp_tool_by_its_server_host(admin_client):
    def change(resources):
        resources["MCPTool"] = [
            {"id": 5, "name": "Ticket lookup", "transport": "https://mcp.example.com:9000/sse", "tool_name": "lookup"}
        ]

    manifest = json.loads(sample_files()["plugin.json"])
    manifest["secret_bindings"].append(
        {"entity": "MCPTool", "ref": 5, "field": "auth_secret", "slot": "OPENAI_API_KEY"}
    )
    content = build_sample_zip(
        replace={"resources.json": _resources_bytes(change), "plugin.json": json.dumps(manifest).encode()}
    )

    slot = _inspect_slot(admin_client, content)

    assert slot["destinations"] == [
        DEFAULT_LLM,
        DEFAULT_EMBEDDINGS,
        {"resource_type": "mcp_tool", "name": "Ticket lookup", "provider": None, "host": "mcp.example.com"},
    ]


@pytest.mark.django_db
def test_inspect_gives_an_unbound_slot_no_destinations(admin_client):
    content = build_sample_zip(manifest_changes={"secret_bindings": []})

    slot = _inspect_slot(admin_client, content)

    assert slot["destinations"] == []


# --- installed plugin (retrieve, list) ----------------------------------------------


@pytest.mark.django_db
def test_retrieve_and_list_show_where_each_slot_is_sent(installed_plugin, admin_client):
    detail = admin_client.get(plugin_url(installed_plugin)).json()
    listing = admin_client.get(PLUGINS_URL).json()

    assert detail["secret_slots"][0]["destinations"] == [DEFAULT_LLM, DEFAULT_EMBEDDINGS]
    assert listing[0]["secret_slots"][0]["destinations"] == [DEFAULT_LLM, DEFAULT_EMBEDDINGS]


@pytest.mark.django_db
def test_retrieve_shows_the_custom_model_host_the_install_kept(
    admin_acme, acme, openai_catalog, storage_backend, admin_client
):
    content = _sample_with_resources(_set_embedding_model_base_url("https://embeddings.example.com"))
    plugin = PluginInstallService().install(upload(content), secrets=SECRETS, user=admin_acme, org_id=acme.pk)

    slot = admin_client.get(plugin_url(plugin)).json()["secret_slots"][0]

    [embedding_model_id] = registered_ids(plugin, "embedding_model")
    assert EmbeddingModel.objects.get(pk=embedding_model_id).base_url == "https://embeddings.example.com"
    assert slot["destinations"] == [DEFAULT_LLM, {**DEFAULT_EMBEDDINGS, "host": "embeddings.example.com"}]


@pytest.mark.django_db
def test_retrieve_follows_edits_and_the_orgs_own_rows_bound_to_the_slot_secret(
    installed_plugin, acme, admin_client
):
    [llm_config_id] = registered_ids(installed_plugin, "llm_config")
    [secret_id] = registered_ids(installed_plugin, "secret")
    plugin_config = LLMConfig.objects.get(pk=llm_config_id)
    LLMConfig.objects.filter(pk=llm_config_id).update(base_url="https://edited.example/v1")
    LLMConfig.objects.create(
        org=acme, custom_name="Mine", model=plugin_config.model, api_key_secret_id=secret_id
    )

    destinations = admin_client.get(plugin_url(installed_plugin)).json()["secret_slots"][0]["destinations"]

    assert destinations == [
        {**DEFAULT_LLM, "host": "edited.example"},
        {"resource_type": "llm_config", "name": "Mine", "provider": "openai", "host": None},
        DEFAULT_EMBEDDINGS,
    ]


@pytest.mark.django_db
def test_retrieve_drops_a_plugin_row_the_org_rebound_to_another_secret(installed_plugin, acme, admin_client):
    [llm_config_id] = registered_ids(installed_plugin, "llm_config")
    other = secret_service.create(text="mine", name="MY_OWN_KEY", org=acme)
    LLMConfig.objects.filter(pk=llm_config_id).update(api_key_secret=other)

    destinations = admin_client.get(plugin_url(installed_plugin)).json()["secret_slots"][0]["destinations"]

    assert destinations == [DEFAULT_EMBEDDINGS]


@pytest.mark.django_db
def test_a_deleted_slot_secret_shows_where_re_entering_it_would_bind(installed_plugin, acme, admin_client):
    Secret.objects.filter(org=acme).delete()

    slot = admin_client.get(plugin_url(installed_plugin)).json()["secret_slots"][0]

    assert slot["configured"] is False
    assert slot["destinations"] == [DEFAULT_LLM, DEFAULT_EMBEDDINGS]


@pytest.mark.django_db
def test_another_orgs_row_bound_to_the_slot_secret_is_never_listed(installed_plugin, beta, admin_client):
    [secret_id] = registered_ids(installed_plugin, "secret")
    plugin_config = LLMConfig.objects.get(pk=registered_ids(installed_plugin, "llm_config")[0])
    # Not reachable through the API; forced here to prove the lookup is scoped to the plugin's org.
    LLMConfig.objects.create(
        org=beta, custom_name="Beta config", model=plugin_config.model, api_key_secret_id=secret_id
    )

    destinations = admin_client.get(plugin_url(installed_plugin)).json()["secret_slots"][0]["destinations"]

    assert destinations == [DEFAULT_LLM, DEFAULT_EMBEDDINGS]
