import pytest
from agents.models import AgentDefinition, Surface
from django.apps import apps

from plugins.models import Plugin, PluginAsset, PluginResource
from plugins.resource_types import RESOURCE_MODELS, PluginResourceType
from plugins.samples.zip_builder import build_sample_zip
from plugins.services.install_service import PluginInstallService
from plugins.services.lifecycle_service import EXTERNAL_USAGES, PluginLifecycleService
from tables.models import (
    DocumentMetadata,
    EmbeddingConfig,
    EmbeddingModel,
    Graph,
    LLMConfig,
    LLMModel,
    Provider,
    Secret,
    Session,
    SourceCollection,
    StorageFile,
)
from tables.models import KeyValueNode, KeyValueTable, KeyValueTableEntry
from tables.models.graph_models import SubGraphNode
from tables.services.key_value_table_service import KeyValueTableService
from tables.services.secrets.secret_service import secret_service
from rbac.models import Role, RolePermission
from rbac.models.enums import Permission
from tests.plugins_tests.helpers import SECRETS, plugin_url, registered_ids, upload

Status = Session.SessionStatus


def _session(graph_id: int, status: str) -> Session:
    return Session.objects.create(graph_id=graph_id, status=status)


@pytest.fixture
def plugin_flow_id(installed_plugin):
    [graph_id] = registered_ids(installed_plugin, "flow")
    yield graph_id


# --- suspend / resume --------------------------------------------------------------


@pytest.mark.django_db
def test_suspend_turns_the_plugin_off_and_stops_its_live_sessions_after_commit(
    installed_plugin, plugin_flow_id, acme, admin_client, stopped_sessions,
    django_capture_on_commit_callbacks,
):
    live = [_session(plugin_flow_id, status) for status in (Status.PENDING, Status.RUN, Status.WAIT_FOR_USER)]
    _session(plugin_flow_id, Status.END)
    other_flow = Graph.objects.create(name="Mine", org=acme)
    _session(other_flow.pk, Status.RUN)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = admin_client.post(plugin_url(installed_plugin, "suspend"))
    assert stopped_sessions == []
    for callback in callbacks:
        callback()

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "suspended"
    assert body["suspended"] is True
    assert body["suspended_at"] is not None
    assert body["state"] == "preparing"
    assert "resources" in body
    assert sorted(stopped_sessions) == sorted(session.pk for session in live)


@pytest.mark.django_db
def test_suspend_is_idempotent(installed_plugin, admin_client, stopped_sessions):
    first = admin_client.post(plugin_url(installed_plugin, "suspend")).json()
    second = admin_client.post(plugin_url(installed_plugin, "suspend"))

    assert second.status_code == 200
    assert second.json()["suspended_at"] == first["suspended_at"]


@pytest.mark.django_db
def test_resume_reverses_suspend(installed_plugin, admin_client, stopped_sessions):
    admin_client.post(plugin_url(installed_plugin, "suspend"))

    response = admin_client.post(plugin_url(installed_plugin, "resume"))
    again = admin_client.post(plugin_url(installed_plugin, "resume"))

    assert response.status_code == 200
    body = response.json()
    assert body["suspended"] is False
    assert body["suspended_at"] is None
    assert body["status"] == body["state"] == "preparing"
    assert again.status_code == 200


# --- delete preview ----------------------------------------------------------------


@pytest.mark.django_db
def test_delete_preview_lists_what_would_go_and_writes_nothing(
    installed_plugin, plugin_flow_id, acme, admin_client
):
    _session(plugin_flow_id, Status.END)
    _session(plugin_flow_id, Status.RUN)
    own = Graph.objects.create(name="My support flow", org=acme)
    SubGraphNode.objects.create(graph=own, subgraph_id=plugin_flow_id, node_name="Chat")

    response = admin_client.get(plugin_url(installed_plugin, "delete-preview"))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["plugin"] == {
        "id": installed_plugin.pk,
        "plugin_id": "chat-bot",
        "name": "Chat Bot",
        "version": "0.1.0",
    }
    assert body["resource_counts"] == {
        "flow": 1,
        "agent_definition": 1,
        "surface": 1,
        "llm_config": 1,
        "embedding_config": 1,
        "secret": 1,
        "source_collection": 1,
        "storage_file": 1,
    }
    assert {resource["type"] for resource in body["resources"]} == set(body["resource_counts"])
    assert all(resource["exists"] for resource in body["resources"])
    assert body["session_count"] == 2
    assert body["live_session_count"] == 1
    assert body["affected_resources"] == {
        "flow": 1,
        "sessions": 2,
        "agent_definitions": 1,
        "surfaces": 1,
        "llm_configs": 1,
        "embedding_configs": 1,
        "secrets": 1,
        "knowledge_collections": 1,
        "knowledge_documents": 2,
        "storage_files": 1,
    }
    assert body["external_usages"] == [
        {
            "type": "flow",
            "resource_id": plugin_flow_id,
            "name": "Chat Bot",
            "used_by": [{"type": "flow", "resource_id": own.pk, "name": "My support flow"}],
        }
    ]
    assert body["missing_permissions"] == []
    assert Graph.objects.filter(pk=plugin_flow_id).exists()
    assert Session.objects.count() == 2


@pytest.mark.django_db
def test_delete_preview_reports_a_row_the_org_deleted_as_missing(installed_plugin, admin_client):
    [surface_id] = registered_ids(installed_plugin, "surface")
    Surface.objects.filter(pk=surface_id).delete()

    body = admin_client.get(plugin_url(installed_plugin, "delete-preview")).json()

    [surface] = [resource for resource in body["resources"] if resource["type"] == "surface"]
    assert surface == {"type": "surface", "resource_id": surface_id, "name": None, "exists": False}
    assert "surface" not in body["resource_counts"]


@pytest.mark.django_db
def test_delete_preview_reports_the_orgs_own_rows_that_use_plugin_parts(
    installed_plugin, acme, admin_client
):
    [llm_config_id] = registered_ids(installed_plugin, "llm_config")
    [secret_id] = registered_ids(installed_plugin, "secret")
    own_agent = AgentDefinition.objects.create(
        organization=acme, name="My agent", llm_config_id=llm_config_id
    )
    own_config = LLMConfig.objects.create(
        org=acme, custom_name="Mine", api_key_secret_id=secret_id, model=LLMConfig.objects.get(pk=llm_config_id).model
    )

    usages = admin_client.get(plugin_url(installed_plugin, "delete-preview")).json()["external_usages"]

    by_type = {usage["type"]: usage["used_by"] for usage in usages}
    assert by_type["llm_config"] == [
        {"type": "agent_definition", "resource_id": own_agent.pk, "name": "My agent"}
    ]
    assert by_type["secret"] == [{"type": "llm_config", "resource_id": own_config.pk, "name": "Mine"}]


@pytest.mark.parametrize("usage", EXTERNAL_USAGES, ids=lambda usage: f"{usage.model_label}.{usage.target_field}")
def test_every_external_usage_names_real_fields(usage):
    model = apps.get_model(usage.model_label)
    target = model._meta.get_field(usage.target_field)

    assert target.related_model is RESOURCE_MODELS[usage.target_type].model
    if usage.owner_field == "id":
        assert model is RESOURCE_MODELS[usage.owner_type].model
    else:
        assert model._meta.get_field(usage.owner_field).related_model is (
            RESOURCE_MODELS[usage.owner_type].model
        )


# --- delete ------------------------------------------------------------------------


def _assert_registered_rows_gone(registry: dict[str, list[int]]) -> None:
    for resource_type, ids in registry.items():
        model = RESOURCE_MODELS[PluginResourceType(resource_type)].model
        assert not model._base_manager.filter(pk__in=ids).exists(), resource_type


def _registry(plugin) -> dict[str, list[int]]:
    return {
        resource_type: registered_ids(plugin, resource_type)
        for resource_type in PluginResource.objects.filter(plugin=plugin)
        .values_list("resource_type", flat=True)
        .distinct()
    }


@pytest.mark.django_db
def test_delete_removes_everything_the_plugin_installed(
    installed_plugin, plugin_flow_id, acme, admin_client, storage_backend, stopped_sessions,
    django_capture_on_commit_callbacks,
):
    registry = _registry(installed_plugin)
    live = _session(plugin_flow_id, Status.RUN)
    [collection_id] = registry["source_collection"]
    key = f"org_{acme.pk}/plugins/chat-bot/tone-guide.md"
    assert key in storage_backend._objects

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(plugin_url(installed_plugin))

    assert response.status_code == 204, response.content
    assert stopped_sessions == [live.pk]
    _assert_registered_rows_gone(registry)
    assert not DocumentMetadata.objects.filter(source_collection_id=collection_id).exists()
    assert not Session.objects.exists()
    assert not StorageFile.objects.filter(org=acme).exists()
    assert key not in storage_backend._objects
    assert not Plugin.objects.exists()
    assert not PluginResource.objects.exists()
    assert not PluginAsset.objects.exists()


@pytest.mark.django_db
def test_delete_leaves_the_orgs_own_same_named_rows_alone(
    acme, admin_acme, admin_client, openai_catalog, storage_backend, sample_zip, stopped_sessions,
):
    own_flow = Graph.objects.create(name="Chat Bot", org=acme)
    own_surface = Surface.objects.create(organization=acme, name="Chat Bot Agent knowledge")
    own_secret = secret_service.create(text="mine", name="OPENAI_API_KEY", org=acme)
    own_collection = SourceCollection.objects.create(collection_name="Acme Notes knowledge", org=acme)
    own_file = StorageFile.objects.create(
        org=acme, path="plugins/chat-bot/my-notes.md", name="my-notes.md", parent_path="plugins/chat-bot/"
    )
    plugin = PluginInstallService().install(
        upload(sample_zip), secrets=SECRETS, user=admin_acme, org_id=acme.pk
    )
    registry = _registry(plugin)

    response = admin_client.delete(plugin_url(plugin))

    assert response.status_code == 204, response.content
    _assert_registered_rows_gone(registry)
    assert Graph.objects.filter(pk=own_flow.pk).exists()
    assert Surface.objects.filter(pk=own_surface.pk).exists()
    assert Secret.objects.filter(pk=own_secret.pk).exists()
    assert SourceCollection.objects.filter(pk=own_collection.pk).exists()
    # The org put its own file in the plugin's folder, so the folder rows stay.
    assert set(StorageFile.objects.filter(org=acme).values_list("path", flat=True)) == {
        own_file.path,
        "plugins/chat-bot/",
        "plugins/",
    }


@pytest.mark.django_db
def test_delete_skips_rows_the_org_already_deleted(
    installed_plugin, admin_client, stopped_sessions
):
    registry = _registry(installed_plugin)
    Surface.objects.filter(pk__in=registry["surface"]).delete()
    Secret.objects.filter(pk__in=registry["secret"]).delete()
    Graph.objects.filter(pk__in=registry["flow"]).delete()

    response = admin_client.delete(plugin_url(installed_plugin))

    assert response.status_code == 204, response.content
    _assert_registered_rows_gone(registry)
    assert not Plugin.objects.exists()


@pytest.mark.django_db
def test_delete_of_another_orgs_plugin_is_404_and_deletes_nothing(
    installed_plugin, beta, role_org_admin, member_of, org_client
):
    client = org_client(member_of(beta, role_org_admin, "admin@beta.test"), beta)

    assert client.delete(plugin_url(installed_plugin)).status_code == 404
    assert client.get(plugin_url(installed_plugin, "delete-preview")).status_code == 404
    assert Plugin.objects.filter(pk=installed_plugin.pk, suspended=False).exists()


# --- custom models the importer had to create --------------------------------------


@pytest.fixture
def provider_without_models(db):
    """An org whose catalog lacks the sample's models: the importer must create them."""
    yield Provider.objects.create(name="openai")


@pytest.mark.django_db
def test_install_links_the_custom_models_it_created_and_delete_removes_them(
    provider_without_models, acme, admin_acme, admin_client, storage_backend, stopped_sessions
):
    plugin = PluginInstallService().install(
        upload(build_sample_zip()), secrets=SECRETS, user=admin_acme, org_id=acme.pk
    )
    [llm_model_id] = registered_ids(plugin, "llm_model")
    [embedding_model_id] = registered_ids(plugin, "embedding_model")
    assert LLMModel.objects.get(pk=llm_model_id).org_id == acme.pk
    assert EmbeddingModel.objects.get(pk=embedding_model_id).org_id == acme.pk

    response = admin_client.delete(plugin_url(plugin))

    assert response.status_code == 204, response.content
    assert not LLMModel.objects.filter(pk=llm_model_id).exists()
    assert not EmbeddingModel.objects.filter(pk=embedding_model_id).exists()


@pytest.mark.django_db
def test_a_custom_model_the_org_adopted_survives_delete(
    provider_without_models, acme, admin_acme, admin_client, storage_backend, stopped_sessions
):
    plugin = PluginInstallService().install(
        upload(build_sample_zip()), secrets=SECRETS, user=admin_acme, org_id=acme.pk
    )
    [llm_model_id] = registered_ids(plugin, "llm_model")
    own_config = LLMConfig.objects.create(org=acme, custom_name="Mine", model_id=llm_model_id)

    preview = admin_client.get(plugin_url(plugin, "delete-preview")).json()
    response = admin_client.delete(plugin_url(plugin))

    assert "llm_model" not in preview["resource_counts"]
    assert preview["resource_counts"]["embedding_model"] == 1
    assert response.status_code == 204, response.content
    assert LLMModel.objects.filter(pk=llm_model_id).exists()
    assert LLMConfig.objects.filter(pk=own_config.pk).exists()


@pytest.mark.django_db
def test_catalog_models_are_never_linked(installed_plugin):
    assert registered_ids(installed_plugin, "llm_model") == []
    assert registered_ids(installed_plugin, "embedding_model") == []
    assert EmbeddingConfig.objects.filter(pk__in=registered_ids(installed_plugin, "embedding_config")).exists()


# --- key-value tables --------------------------------------------------------------

CHAT_ADMIN_TABLE = "chat_admin__conversations"


@pytest.fixture
def plugin_table(chat_admin_plugin, acme):
    """The chat-admin plugin's table, holding two conversations."""
    table = KeyValueTable.objects.get(org=acme, name=CHAT_ADMIN_TABLE)
    KeyValueTableService().write(table, {"c_1": {"turns": 1}, "c_2": {"turns": 3}})
    yield table


@pytest.fixture
def own_flow_using_the_table(acme, plugin_table):
    """A flow of the org itself that reads the plugin's table."""
    graph = Graph.objects.create(name="Conversation report", org=acme)
    node = KeyValueNode.objects.create(
        graph=graph,
        node_name="Read",
        key_value_table=plugin_table,
        entries=[{"key": "c_1", "value": "variables.conversation"}],
    )
    yield graph, node


@pytest.mark.django_db
def test_delete_preview_counts_the_table_and_reports_the_orgs_flow_using_it(
    chat_admin_plugin, plugin_table, own_flow_using_the_table, admin_client
):
    own_flow, _ = own_flow_using_the_table

    body = admin_client.get(plugin_url(chat_admin_plugin, "delete-preview")).json()

    assert body["resource_counts"]["key_value_table"] == 1
    assert body["affected_resources"]["key_value_tables"] == 1
    assert {"type": "key_value_table", "resource_id": plugin_table.pk, "name": CHAT_ADMIN_TABLE, "exists": True} in body["resources"]
    assert {
        "type": "key_value_table",
        "resource_id": plugin_table.pk,
        "name": CHAT_ADMIN_TABLE,
        "used_by": [{"type": "flow", "resource_id": own_flow.pk, "name": "Conversation report"}],
    } in body["external_usages"]


@pytest.mark.django_db
def test_the_plugins_own_flow_is_not_an_external_usage_of_its_table(
    chat_admin_plugin, plugin_table, admin_client
):
    body = admin_client.get(plugin_url(chat_admin_plugin, "delete-preview")).json()

    assert body["external_usages"] == []


@pytest.mark.django_db
def test_delete_removes_the_table_and_its_rows_and_unlinks_the_orgs_node(
    chat_admin_plugin, plugin_table, own_flow_using_the_table, admin_client, stopped_sessions
):
    own_flow, own_node = own_flow_using_the_table

    response = admin_client.delete(plugin_url(chat_admin_plugin))

    assert response.status_code == 204, response.content
    assert not KeyValueTable.objects.filter(pk=plugin_table.pk).exists()
    assert not KeyValueTableEntry.objects.filter(table_id=plugin_table.pk).exists()
    own_node.refresh_from_db()
    assert own_node.key_value_table_id is None
    assert Graph.objects.filter(pk=own_flow.pk).exists()
    assert not Plugin.objects.exists()


@pytest.mark.django_db
def test_delete_needs_delete_on_key_value_tables(
    chat_admin_plugin, plugin_table, acme, member_of, org_client
):
    role = Role.objects.create(name="Remover without tables", org=acme, is_built_in=False)
    RolePermission.objects.create(role=role, resource_type="plugins", permissions=255)
    for resource_type in ("flows", "agents", "llm_configs", "secrets"):
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(Permission.READ | Permission.DELETE)
        )
    client = org_client(member_of(acme, role, "remover@acme.test"), acme)

    preview = client.get(plugin_url(chat_admin_plugin, "delete-preview")).json()
    response = client.delete(plugin_url(chat_admin_plugin))

    assert preview["missing_permissions"] == [{"resource_type": "key_value_tables", "action": "delete"}]
    assert response.status_code == 403, response.content
    assert response.json()["errors"] == [{"resource_type": "key_value_tables", "action": "delete"}]
    assert KeyValueTable.objects.filter(pk=plugin_table.pk).exists()
    assert plugin_table.entries.count() == 2
    assert Plugin.objects.filter(pk=chat_admin_plugin.pk, suspended=False).exists()


@pytest.mark.django_db
def test_a_table_deleted_concurrently_does_not_abort_the_plugin_delete(
    chat_admin_plugin, plugin_table, admin_client, stopped_sessions, monkeypatch
):
    """The table is gone by the time delete reaches it, after the registry was loaded."""
    delete_table = KeyValueTableService.delete_table

    def _deleted_meanwhile(service, table):
        KeyValueTable.objects.filter(pk=table.pk).delete()
        return delete_table(service, table)

    monkeypatch.setattr(KeyValueTableService, "delete_table", _deleted_meanwhile)

    response = admin_client.delete(plugin_url(chat_admin_plugin))

    assert response.status_code == 204, response.content
    assert not Plugin.objects.exists()
    assert not KeyValueTable.objects.filter(pk=plugin_table.pk).exists()


@pytest.mark.django_db
def test_delete_skips_a_table_the_org_already_deleted(
    chat_admin_plugin, plugin_table, admin_client, stopped_sessions
):
    KeyValueTableService().delete_table(plugin_table)

    response = admin_client.delete(plugin_url(chat_admin_plugin))

    assert response.status_code == 204, response.content
    assert not Plugin.objects.exists()
